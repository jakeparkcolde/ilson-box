"""팩 설치·렌더가 실제 완료와 사용자 승인에 연결되는지 확인한다."""
import json
from pathlib import Path
from unittest.mock import patch
from test_current_ui import CurrentUITests
from test_current_http import CurrentHTTPTests
from mini_workspace import WorkspaceError
import motion_pack as motion

class MotionTests(CurrentUITests):
    def test_설치실패는_연결완료가되지않고_재시도가능(self):
        self.provider.motion_install=lambda *a: (_ for _ in ()).throw(WorkspaceError('도구 설치 실패'))
        queued=self.ui.dispatch('POST','/api/motion/install',data={})
        with self.assertRaises(WorkspaceError):self.ui.dispatch('POST','/api/motion/install',data={})
        self.work.run_next_job()
        state=self.ui.dispatch('GET','/api/motion/status')
        self.assertFalse(state['installed']);self.assertEqual(state['jobs'][0]['status'],'failed')
        self.assertEqual(state['jobs'][0]['error'],'도구 설치 실패')
        self.ui.dispatch('POST','/api/motion/install',data={})

    def test_렌더승인과_작품경로를_확인(self):
        key='a'*32;(self.home/'projects/motion'/key).mkdir(parents=True)
        with self.assertRaises(WorkspaceError):self.ui.dispatch('POST','/api/motion/render',data={'project_id':key})
        with self.assertRaises(WorkspaceError):self.ui.dispatch('POST','/api/motion/render',data={'project_id':'../../vault','approved':True})
        self.provider.motion_render=lambda *a:{'project_id':key,'download':True}
        q=self.ui.dispatch('POST','/api/motion/render',data={'project_id':key,'approved':True});self.work.run_next_job()
        self.assertEqual(self.work.job(q['id'])['status'],'done')
        self.assertEqual(self.work.documents()['documents'],[])

    def test_사용자문구는_HTML이나_스크립트가되지않음(self):
        scenes=motion.validate_scenes({'scenes':[{'title':'<script>alert(1)</script>','body':'안내'},{'title':'두 번째','body':'설명'}]})
        body=motion.composition(scenes,15,'')
        self.assertIn('&lt;script&gt;',body);self.assertNotIn('<script>alert(1)</script>',body)
        with self.assertRaises(WorkspaceError):motion.validate_scenes({'scenes':[{'title':'x','body':'y'}]})

    def test_설치명령실패시_완료표식없음(self):
        with patch.object(motion,'run',side_effect=WorkspaceError('설치 실패')):
            with self.assertRaises(WorkspaceError):motion.install(self.home,{},lambda **kw:None)
        self.assertFalse(motion.status(self.home)['installed'])

class MotionHTTPTests(CurrentHTTPTests):
    def test_팩설치와_영상다운로드도_인증필요(self):
        key='a'*32;p=self.home/'projects/motion'/key;p.mkdir(parents=True);(p/'output.mp4').write_bytes(b'test-video')
        url=f'/api/motion/projects/{key}/download'
        self.assertEqual(self.call('GET','/api/motion/status',cookie=False)[0],401)
        self.assertEqual(self.call('POST','/api/motion/install',data={},cookie=False)[0],401)
        self.assertEqual(self.call('POST','/api/motion/install',data={},origin='https://evil.example')[0],403)
        self.assertEqual(self.call('GET',url,cookie=False)[0],401)
        self.assertEqual(self.call('GET',url)[2],b'test-video')

class MotionDependencyTests(__import__('unittest').TestCase):
    def test_준비된프로그램은_재설치하지않음(self):
        with patch.object(motion,'dependencies',return_value={'Node.js':True,'Chrome':True}),patch.object(motion,'status',return_value={'installed':True}),patch.object(motion,'install') as install:
            motion.ensure(Path('/tmp'));install.assert_not_called()
    def test_완료표식이있어도_누락프로그램을_복구(self):
        with patch.object(motion,'dependencies',side_effect=[{'FFmpeg':False},{'FFmpeg':True}]),patch.object(motion,'status',return_value={'installed':True}),patch.object(motion,'install') as install:
            motion.ensure(Path('/tmp'));install.assert_called_once()
    def test_복구후_프로그램검증실패는_완료가아님(self):
        with patch.object(motion,'dependencies',return_value={'FFmpeg':False}),patch.object(motion,'install'):
            with self.assertRaises(WorkspaceError):motion.ensure(Path('/tmp'))
