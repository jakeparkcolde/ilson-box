"""Isolated course processes; no real browser, account, or OS service."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'template/lib'))
import course_admin as launch
import ilson_platform as platform


class CourseLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.home=self.root/'state-home';self.vault=self.root/'notes';self.vault.mkdir()
        self.library=self.root/'code/lib';self.library.mkdir(parents=True)
        for name in ('web-admin-server.py','ilson_platform.py','access_policy.py','approval_actions.py','approval_dispatch.py','approval_store.py','runtime_gate.py','course_admin.py'):
            shutil.copy2(ROOT/'template/lib'/name,self.library/name)
        (self.library/'license.py').write_text("def evaluate(home): return True, 'ACTIVE'\n")
        self.patch=patch.object(launch,'LIBRARY',self.library);self.patch.start();self.addCleanup(self.patch.stop)
        self.addCleanup(self.cleanup_server)

    def cleanup_server(self):
        try:
            _,private=launch.private_home(self.home)
            if launch.locked(private): launch.stop(self.home,force=True)
        except (ValueError,OSError): pass

    def test_real_first_start_reuse_port_occupation_stale_state_and_shutdown(self):
        occupied=socket.socket();occupied.bind(('127.0.0.1',0));occupied.listen();self.addCleanup(occupied.close)
        port=launch.start(self.home,self.vault,port=occupied.getsockname()[1])
        self.assertNotEqual(port,occupied.getsockname()[1])
        _,private=launch.private_home(self.home);first=launch.record(private)
        self.assertTrue(launch.health(first));self.assertTrue(launch.locked(private))
        self.assertEqual(launch.start(self.home,self.vault),port)
        self.assertEqual(launch.record(private)['pid'],first['pid'])
        self.assertEqual(launch.status(self.home),0)
        launch.stop(self.home);self.assertFalse(launch.locked(private));self.assertFalse((private/'server.json').exists())
        # A valid but stale record is replaced when its process no longer holds the lock.
        platform.atomic_write(private/'server.json',json.dumps(first).encode())
        second_port=launch.start(self.home,self.vault)
        second=launch.record(private);self.assertNotEqual(second['pid'],first['pid']);self.assertTrue(launch.health(second))
        launch.stop(self.home)

    def test_idle_exit_removes_listener_record_and_releases_os_lock(self):
        port=launch.start(self.home,self.vault,idle_seconds=.4)
        _,private=launch.private_home(self.home)
        launch.wait_stopped(private,wait=5)
        self.assertFalse((private/'server.json').exists())
        with self.assertRaises(OSError): socket.create_connection(('127.0.0.1',port),timeout=.2)

    def test_concurrent_launcher_is_rejected_without_spawning_and_no_token_in_args(self):
        _,private=launch.private_home(self.home)
        fd=platform.acquire_lock(private/'launcher.lock')
        try:
            with patch.object(launch.subprocess,'Popen') as popen:
                with self.assertRaises(launch.CourseAdminError): launch.start(self.home,self.vault)
                popen.assert_not_called()
        finally: os.close(fd)
        real=subprocess.Popen
        captured=[]
        def spawn(args,**kwargs): captured.append((args,kwargs));return real(args,**kwargs)
        with patch.object(launch.subprocess,'Popen',side_effect=spawn): port=launch.start(self.home,self.vault)
        token=launch.read(private,'token')
        self.assertNotIn(token,json.dumps(captured[0][0]));self.assertNotIn(token,json.dumps(captured[0][1]['env']))
        info=launch.record(private)
        with patch.object(launch.os,'startfile',create=True) as startfile,patch.object(platform,'IS_WINDOWS',True),patch.object(launch,'private_home',return_value=(self.home,private)),patch.object(launch,'record',return_value=info),patch.object(launch,'health',return_value=True),patch.object(launch,'read',return_value=token):
            launch.open_browser(self.home,port)
            self.assertIn('#token=',startfile.call_args.args[0])

    def test_code_digest_change_replaces_our_server_and_force_refuses_other_identity(self):
        launch.start(self.home,self.vault);_,private=launch.private_home(self.home);first=launch.record(private)
        (self.library/'new_feature.py').write_text('# updated\n')
        launch.start(self.home,self.vault);second=launch.record(private)
        self.assertNotEqual(first['pid'],second['pid'])
        with patch.object(launch,'health',return_value=False),patch.object(platform,'process_identity',return_value=('/other/python',second['started_at'])),patch.object(launch.os,'kill') as kill:
            with self.assertRaises(launch.CourseAdminError): launch.stop(self.home,force=True)
            kill.assert_not_called()


    def test_only_authenticated_heartbeat_keeps_idle_server_alive(self):
        port=launch.start(self.home,self.vault,idle_seconds=.5)
        _,private=launch.private_home(self.home);info=launch.record(private)
        cookie=launch.authenticate(private,info)
        for _ in range(5):
            time.sleep(.15)
            launch.request(port,'/api/session',cookie=cookie)
        self.assertTrue(launch.locked(private))
        launch.wait_stopped(private,wait=3)

    def test_shutdown_requires_session_and_same_origin(self):
        port=launch.start(self.home,self.vault)
        with self.assertRaises(launch.CourseAdminError): launch.request(port,'/api/admin/shutdown',body={})
        _,private=launch.private_home(self.home);self.assertTrue(launch.locked(private))


    def test_code_install_lock_prevents_starting_partial_upgrade(self):
        fd=platform.acquire_lock(self.library/'.install.lock')
        try:
            with patch.object(launch.subprocess,'Popen') as popen:
                with self.assertRaises(BlockingIOError):launch.start(self.home,self.vault)
                popen.assert_not_called()
        finally:os.close(fd)

    def test_expired_license_keeps_shutdown_and_local_privacy_api_available(self):
        (self.library/'license.py').write_text("def evaluate(home): return False, 'EXPIRED'\n")
        shutil.copy2(ROOT/'course/lib/usage_timeline.py',self.library/'usage_timeline.py')
        port=launch.start(self.home,self.vault)
        _,private=launch.private_home(self.home);info=launch.record(private);cookie=launch.authenticate(private,info)
        with self.assertRaises(launch.CourseAdminError):launch.request(port,'/api/overview',cookie=cookie)
        data,_=launch.request(port,'/api/usage-history/summary',cookie=cookie)
        self.assertEqual(data['state'],'off')
        launch.stop(self.home);self.assertFalse(launch.locked(private))


    def test_one_code_bundle_cannot_start_a_second_state_while_active(self):
        launch.start(self.home,self.vault)
        _,private=launch.private_home(self.home);first=launch.record(private)
        with self.assertRaises(launch.CourseAdminError):launch.start(self.root/'other-state',self.vault)
        self.assertTrue(launch.health(first))
        launch.stop(self.home)
        fd=platform.acquire_lock(self.library/'.admin.lock');os.close(fd)
