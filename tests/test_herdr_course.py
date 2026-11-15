"""Windows course app pins and diagnosis; native PowerShell behavior stays explicit."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('herdr_course_diag',ROOT/'course/lib/install_diagnostics.py')
diag=importlib.util.module_from_spec(spec);spec.loader.exec_module(diag)


class HerdrContractTests(unittest.TestCase):
    def test_windows_uses_official_fixed_archive_and_never_installs_or_removes_orca(self):
        source=(ROOT/'course/install-windows.ps1').read_text(encoding='ascii')
        pin=json.loads((ROOT/'course/herdr-windows-source.json').read_text())
        self.assertEqual(pin['version'],'0.1.15')
        self.assertTrue(pin['url'].startswith('https://releases.herdr.dev/app/'+pin['version']+'/'))
        self.assertRegex(pin['sha256'],r'^[a-f0-9]{64}$')
        for value in (pin['url'],pin['sha256'],pin['version']):self.assertIn("'"+value+"'",source)
        self.assertIn("Start-IlsonStep 'apps.herdr'",source)
        self.assertNotIn("Start-IlsonStep 'apps.orca'",source)
        self.assertNotIn('orca-windows-setup.exe',source)
        self.assertNotIn('Find-Orca',source)
        helper=source.split('# HERDR_COURSE_BEGIN',1)[1].split('# HERDR_COURSE_END',1)[0]
        self.assertNotIn('Orca',helper)
        self.assertIn('Get-FileHash',helper);self.assertIn('Get-AuthenticodeSignature',helper)
        self.assertIn('WaitForExit(5000)',helper)
        self.assertIn('DoNotExpandEnvironmentNames',helper)
        self.assertIn("$key.GetValueKind('Path')",helper)
        self.assertIn('[IO.Directory]::Move',helper)
        self.assertIn('if ($Plan)',helper)
        download=source.split('function Get-IlsonDownload',1)[1].split('function Complete-IlsonDiagnostics',1)[0]
        self.assertIn("'releases.herdr.dev'",download)
        intel=(ROOT/'course/install-intel-mac.sh').read_text()
        self.assertIn('orca-macos-x64.dmg',intel)
        self.assertFalse(pin['intel_macos_supported'])

    def test_current_windows_messages_and_guide_distinguish_intel(self):
        source=(ROOT/'course/install-windows.ps1').read_text(encoding='ascii')
        texts=[base64.b64decode(v).decode() for v in re.findall(r"(?<=K ')[A-Za-z0-9+/=]+(?=')",source)]
        self.assertTrue(any('Herdr' in text for text in texts))
        self.assertFalse(any('Orca' in text for text in texts))
        guide=(ROOT/'course/00_강의_시작.md').read_text()
        self.assertIn('Herdr(Windows)·Orca(Intel Mac)',guide)
        doctor=(ROOT/'tools/doctor.ps1').read_text()
        self.assertIn('workspace_app=Herdr',doctor)
        self.assertNotIn('Find-Orca',doctor)

    def test_windows_doctor_checks_herdr_version_and_never_checks_orca(self):
        with tempfile.TemporaryDirectory() as temp:
            app=Path(temp)/'Programs/herdr-app/herdr-app.exe';app.parent.mkdir(parents=True);app.write_text('fixture')
            proxy=SimpleNamespace(**{key:getattr(os,key) for key in dir(os) if not key.startswith('__')});proxy.name='nt'
            with patch.object(diag,'os',proxy),patch.dict(os.environ,{'LOCALAPPDATA':temp,'ProgramFiles':str(Path(temp)/'programfiles')}),patch.object(diag.shutil,'which',return_value=None),patch.object(diag,'probe_command',return_value=(0,b'herdr-app 0.1.15\r\n')) as probe:
                value=diag.course_workspace_app()
                self.assertEqual(value,{'name':'Herdr','state':'present','version':'0.1.15'})
                self.assertEqual(probe.call_args.args[0],[str(app),'--version'])
                probe.return_value=(0,b'unknown or secret');self.assertEqual(diag.course_workspace_app()['state'],'unknown')
                app.unlink();self.assertEqual(diag.course_workspace_app()['state'],'missing')

    @unittest.skipUnless(shutil.which('pwsh'),'pwsh required for native stderr handling')
    def test_native_stderr_keeps_success_and_failure_exit_codes(self):
        source=(ROOT/'course/install-windows.ps1').read_text(encoding='ascii')
        helper=source.split('function Invoke-IlsonCourseNative',1)[1].split('function Find-Herdr',1)[0]
        script='function Invoke-IlsonCourseNative'+helper+r'''
$ErrorActionPreference='Stop'
foreach ($code in @(0,7)) {
    $result=Invoke-IlsonCourseNative $env:ILSON_TEST_PYTHON @('-c', ('import sys; print("native-ok"); print("private-warning",file=sys.stderr); sys.exit('+ $code +')'))
    if ($ErrorActionPreference -ne 'Stop') { throw 'preference changed' }
    if ($result.ExitCode -ne $code -or ($result.Output -join '') -ne 'native-ok') { throw 'native result lost' }
    Write-Output ('verified '+$result.ExitCode)
}
'''
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'native.ps1';path.write_text(script,encoding='ascii')
            result=subprocess.run([shutil.which('pwsh'),'-NoProfile','-File',str(path)],env=dict(os.environ,ILSON_TEST_PYTHON=sys.executable),capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(result.stdout.splitlines(),['verified 0','verified 7'])
            self.assertNotIn('private-warning',result.stdout+result.stderr)

    @unittest.skipUnless(shutil.which('pwsh'),'pwsh required for isolated PowerShell Herdr modes')
    def test_powershell_dry_run_reuse_and_failed_download_continue_without_orca(self):
        source=(ROOT/'course/install-windows.ps1').read_text(encoding='ascii')
        helper=source.split('# HERDR_COURSE_BEGIN',1)[1].split('# HERDR_COURSE_END',1)[0]
        stage="    Start-IlsonStep 'apps.herdr'\n"+source.split("    Start-IlsonStep 'apps.herdr'\n",1)[1].split("    $obsUrl =",1)[0]
        for mode in ('dry','reuse','failure'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as temp:
                home=Path(temp);tar=home/'system/System32/tar.exe';tar.parent.mkdir(parents=True);tar.write_text('unused')
                mocks=r'''
function K($s) { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($s)) }
function Test-IlsonDiagPath($p) { }
function Start-IlsonStep($s) { }
function Stop-IlsonStep($s,$result,$reason) { Write-Output ('EVENT '+$s+' '+$result+' '+$reason) }
function Get-IlsonDownload { throw 'fixture failed download' }
function Find-Herdr { EXISTING }
function Get-HerdrCourseVersion { '0.1.15' }
$statuses=@{};$arch='x64-based PC';$DryRun=PLAN
'''.replace('EXISTING',"'/fake/herdr-app.exe'" if mode=='reuse' else '$null').replace('PLAN','$true' if mode=='dry' else '$false')
                script=home/'run.ps1';script.write_text(helper+'\n'+mocks+'\n'+stage+"\nWrite-Output 'NEXT_OBSIDIAN_STEP'\n",encoding='ascii')
                result=subprocess.run([shutil.which('pwsh'),'-NoProfile','-File',str(script)],env=dict(os.environ,LOCALAPPDATA=str(home),USERPROFILE=str(home),ProgramFiles=str(home/'programfiles'),SystemRoot=str(home/'system')),capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn('NEXT_OBSIDIAN_STEP',result.stdout)
                expected={'dry':'Herdr: Planned 0.1.15','reuse':'Herdr: Reused 0.1.15','failure':'Herdr: DETAIL_SUPPRESSED'}[mode]
                self.assertIn(expected,result.stdout)
                self.assertNotIn('fixture failed download',result.stdout)
                self.assertFalse((home/'Programs/orca').exists())
