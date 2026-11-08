from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'template/lib'))
import approval_service as service


class ApprovalServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.home=self.root/'box'; self.home.mkdir(); self.agents=self.root/'agents'; self.agents.mkdir()
        self.calls=[]
    def run_launchctl(self,args,**kwargs):
        self.calls.append(args)
        class Result: returncode=1 if args[1]=='print' else 0
        return Result()
    def test_install_sets_home_and_stop_preserves_plist(self):
        with patch.object(service.sys,'platform','darwin'), patch.object(service.subprocess,'run',side_effect=self.run_launchctl):
            service.manage('install',self.home,agents=self.agents,launchctl='fake')
            path=self.agents/'com.ilson.approval.plist'
            config=plistlib.loads(path.read_bytes())
            self.assertEqual(config['EnvironmentVariables']['ILSON_HOME'],str(self.home.resolve()))
            service.manage('stop',self.home,agents=self.agents,launchctl='fake')
        self.assertTrue(path.exists())
        self.assertIn('disable',[c[1] for c in self.calls])
    def test_update_reloads_only_owned_receiver(self):
        class Running: returncode=0
        with patch.object(service.sys,'platform','darwin'), patch.object(service.subprocess,'run',side_effect=self.run_launchctl):
            service.manage('install',self.home,agents=self.agents,launchctl='fake')
        self.calls.clear()
        def running(args, **kwargs): self.calls.append(args); return Running()
        with patch.object(service.sys,'platform','darwin'), patch.object(service.subprocess,'run',side_effect=running):
            service.manage('install',self.home,agents=self.agents,launchctl='fake')
        self.assertEqual([call[1] for call in self.calls],['print','bootout','enable','bootstrap'])
        self.assertTrue(all('com.ilson.approval' in ' '.join(call) for call in self.calls))
    def test_other_box_is_not_stopped_or_overwritten(self):
        path=self.agents/'com.ilson.approval.plist'
        path.write_bytes(plistlib.dumps({'Label':'com.ilson.approval','ProgramArguments':['python','/other/lib/approval_telegram.py','--home','/other']}))
        original=path.read_bytes()
        with patch.object(service.sys,'platform','darwin'), patch.object(service.subprocess,'run',side_effect=self.run_launchctl):
            with self.assertRaises(ValueError): service.manage('install',self.home,agents=self.agents,launchctl='fake')
        self.assertEqual(path.read_bytes(),original)
        self.assertEqual([c[1] for c in self.calls],['print'])

if __name__=='__main__': unittest.main()
