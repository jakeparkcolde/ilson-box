"""License gates against isolated copies with an RFC test key, no real credentials."""
import importlib.util
import datetime
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
SEED=bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60')
PUBLIC='d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a'

class Integration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.repo=self.root/'repo'; self.repo.mkdir()
        shutil.copy2(ROOT/'ilson',self.repo/'ilson')
        shutil.copytree(ROOT/'template',self.repo/'template',ignore=shutil.ignore_patterns('__pycache__'))
        p=self.repo/'template/lib/license.py'
        p.write_text(p.read_text().replace('PUBLIC_KEYS = {}',f"PUBLIC_KEYS = {{1: bytes.fromhex('{PUBLIC}')}}"))
        spec=importlib.util.spec_from_file_location('fixture_license',p); self.license=importlib.util.module_from_spec(spec); spec.loader.exec_module(self.license)
        self.box=self.root/'box'; self.env={**os.environ,'HOME':str(self.root),'ILSON_HOME':str(self.box)}
    def command(self,*args):
        return subprocess.run(['bash',str(self.repo/'ilson'),*args],env=self.env,text=True,capture_output=True,timeout=15)
    def activate(self):
        now=int(time.time()); payload=struct.pack('>BB16sHBII',1,1,b't'*16,1,1,now-10,now+86400)
        serial=self.license.encode_serial(payload,SEED)
        ok,_=self.license.evaluate(self.box,serial,transport=lambda *_: (_ for _ in ()).throw(OSError('offline')))
        self.assertTrue(ok)
    def test_unlicensed_command_blocked_but_help_and_install_kit_allowed(self):
        result=self.command('course-kit')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('NO_LICENSE',result.stdout)
        self.assertFalse((self.box/'강의키트-20261109-v2').exists())
        kit=subprocess.run(['python3',str(self.repo/'template/lib/course-kit.py'),str(self.repo/'template/claude/skills/course-kit-20261109'),str(self.box)],env=self.env,capture_output=True,text=True)
        self.assertEqual(kit.returncode,0,kit.stderr)
        self.assertTrue((self.box/'강의키트-20261109-v2').is_dir())
        self.assertIn('사용법',self.command('--help').stdout)
    def test_issuer_creates_only_test_key_and_private_serial_in_temporary_home(self):
        issuer=ROOT/'server/license/issuer.py'
        def call(*args):
            return subprocess.run(['python3',str(issuer),*args],env=self.env,text=True,capture_output=True)
        init=call('init-key'); self.assertEqual(init.returncode,0,init.stderr)
        config=self.root/'.config/ilson-license'; key=config/'signing-key'
        self.assertEqual(key.stat().st_mode & 0o777,0o600)
        self.assertNotIn(key.read_text().strip(),init.stdout)
        now=datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        out=config/'sample.serial'
        result=call('issue','--key',str(key),'--output',str(out),'--kid','1','--cohort','1',
                    '--plan','one-time','--issued',now.isoformat(),'--expires',(now+datetime.timedelta(days=3650)).isoformat())
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(out.stat().st_mode & 0o777,0o600)
        serial=out.read_text().strip(); self.assertNotIn(serial,result.stdout)
        self.license.PUBLIC_KEYS[1]=self.license.public_key(bytes.fromhex(key.read_text().strip()))
        self.assertEqual(self.license.parse_serial(serial)['plan'],1)
        self.assertNotEqual(call('init-key').returncode,0)
    def test_active_course_kit_preserves_user_file(self):
        self.activate(); kit=self.box/'강의키트-20261109-v2'; kit.mkdir()
        note=kit/'내 업무 소개.md'; note.write_text('개인 수정')
        result=self.command('course-kit')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(note.read_text(),'개인 수정')
        self.assertTrue((kit/'시작과_막힘_복구.md').is_file())
    def test_help_anywhere_never_executes_motion_research_or_nested_commands(self):
        for args in (('motion','-h'),('motion','영상 요청','--help'),('research','run','-h'),('people','add','--help')):
            with self.subTest(args=args):
                result=self.command(*args)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn('사용법:',result.stdout)
        self.assertFalse((self.box/'state/license').exists())
    def test_unlicensed_watchdog_suppresses_missed_job_alert(self):
        (self.box/'lib').mkdir(parents=True)
        (self.box/'state').mkdir()
        for f in ('license.py','watchdog.sh','common.sh'):
            shutil.copy2(self.repo/'template/lib'/f,self.box/'lib'/f)
        marker=self.box/'state/enabled.briefing'; marker.touch()
        old=time.time()-4*86400; os.utime(marker,(old,old))
        capture=self.root/'notify.txt'
        (self.box/'lib/notify.sh').write_text('#!/bin/sh\necho alert > "'+str(capture)+'"\n')
        result=subprocess.run(['bash',str(self.box/'lib/watchdog.sh')],env=self.env,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(capture.exists())
        self.assertFalse(list((self.box/'state').glob('alerted.briefing.*')))
    def test_unlicensed_scheduled_job_skips_and_logs(self):
        (self.box/'lib').mkdir(parents=True)
        for f in ('license.py','run-job.sh','common.sh'):
            shutil.copy2(self.repo/'template/lib'/f,self.box/'lib'/f)
        result=subprocess.run(['bash',str(self.box/'lib/run-job.sh'),'briefing'],env=self.env,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('skipped: license required',(self.box/'logs/briefing.log').read_text())
        self.assertFalse((self.box/'state/last-run.briefing').exists())

if __name__=='__main__': unittest.main()
