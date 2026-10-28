"""사진의 디코딩·인증·경로·가산보존 계약. 외부 이미지/모델 없음."""
import base64
import io
import subprocess
import unittest
from PIL import Image
import test_people_skills as base
import test_mini_workspace as fixtures
import test_web_admin as http
from mini_workspace import Workspace, WorkspaceError


def photo(fmt='PNG',size=(64,48)):
    out=io.BytesIO();Image.new('RGB',size,(80,140,160)).save(out,format=fmt)
    return {'media_type':'image/png' if fmt=='PNG' else 'image/jpeg','data':base64.b64encode(out.getvalue()).decode()}


class AvatarTests(unittest.TestCase):
    setUp=base.PeopleTests.setUp
    employee=base.PeopleTests.employee

    def test_replace_remove_delete_and_reopen(self):
        e=self.employee();self.assertEqual(self.people.state()['avatars'],[])
        a=self.people.avatar({'employee_id':e,'expected':'','image':photo()})
        raw=self.people.avatar_image(e+'/'+a['revision'])
        with Image.open(io.BytesIO(raw)) as im:
            self.assertEqual(im.format,'JPEG');self.assertFalse(im.getexif());self.assertLessEqual(max(im.size),512)
        with self.assertRaises(WorkspaceError):self.people.avatar({'employee_id':e,'expected':'','image':photo()})
        b=self.people.avatar({'employee_id':e,'expected':a['revision'],'image':photo('JPEG')})
        with self.assertRaises(WorkspaceError):self.people.avatar_image(e+'/'+a['revision'])
        self.work.close();self.work=Workspace(self.home,fixtures.admin.Files(self.home));self.people=self.work.people
        self.assertTrue(self.people.avatar_image(e+'/'+b['revision']))
        self.people.avatar({'employee_id':e,'expected':b['revision'],'choice':'face-6'})
        with self.assertRaises(WorkspaceError):self.people.avatar_image(e+'/'+b['revision'])
        self.assertEqual(self.people.state()['avatars'][0]['choice'],'face-6')
        self.people.delete('employees',e);self.assertEqual(self.work.db.execute('SELECT count(*) FROM people_avatars').fetchone()[0],0)

    def test_invalid_images_paths_no_mutation(self):
        e=self.employee();good=photo();original=self.people.state()
        bad=[{'media_type':'image/svg+xml','data':base64.b64encode(b'<svg onload="x"/>').decode()},
             {'media_type':'image/jpeg','data':good['data']},{'media_type':'image/png','data':'!'},
             {'media_type':'image/png','data':'A'*2796205},photo(size=(2001,2000)),
             {'media_type':'image/jpeg','data':photo('JPEG')['data'][:-20]}, {'url':'https://example.com/a.png'}]
        for value in bad:
            with self.subTest(value=str(value)[:50]),self.assertRaises(WorkspaceError):self.people.avatar({'employee_id':e,'expected':'','image':value})
        for key in ('../../x','file:///x','https://x','a'*32+'/../../x'):
            with self.assertRaises(WorkspaceError):self.people.avatar_image(key)
        with self.assertRaises(WorkspaceError):self.people.avatar({'employee_id':e,'expected':'','choice':'<svg>'})
        with self.assertRaises(WorkspaceError):self.people.avatar({'employee_id':e,'expected':'','path':'../../x'})
        self.assertEqual(self.people.state(),original)

    def test_update_rollback_preserves_photo_bytes(self):
        import test_update
        f=test_update.UpdateTests();f.setUp();self.addCleanup(f.doCleanups)
        work=Workspace(f.roots['box'],fixtures.admin.Files(f.roots['box']))
        e=work.people.save('employees',{'name':'보존 시험','role':'검토'})['id']
        a=work.people.avatar({'employee_id':e,'expected':'','image':photo()})
        image=work.people.avatar_image(e+'/'+a['revision']);work.close()
        db=f.roots['box']/'.workspace/work.sqlite3';raw=db.read_bytes()
        manifest,archive=f.bundle([('box','web/current/people.js',(fixtures.ROOT/'template/web/current/people.js').read_bytes(),None)])
        test_update.u.apply(f.roots,manifest,archive);self.assertEqual(db.read_bytes(),raw)
        store=f.roots['box']/'.updates';test_update.u.rollback(f.roots,store,test_update.u.read(store/'journal.json'));self.assertEqual(db.read_bytes(),raw)
        work=Workspace(f.roots['box'],fixtures.admin.Files(f.roots['box']))
        try:self.assertEqual(work.people.avatar_image(e+'/'+a['revision']),image)
        finally:work.close()

    def test_layout_controls_templates_preserve_draft(self):
        result=subprocess.run(['node',str(fixtures.ROOT/'tests/people_layout_check.js')],cwd=fixtures.ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_previous_code_write_preserves_image(self):
        e=self.employee();a=self.people.avatar({'employee_id':e,'expected':'','image':photo()});raw=self.people.avatar_image(e+'/'+a['revision'])
        source=subprocess.check_output(['git','show','377d55e:template/lib/people_skills.py'],cwd=fixtures.ROOT,text=True)
        namespace={};exec(compile(source,'old_people','exec'),namespace);old=namespace['People'](self.work)
        old.save('employees',{'id':e,'name':'구버전 수정','role':'검토','department_id':'','active':True})
        self.assertEqual(self.people.avatar_image(e+'/'+a['revision']),raw)


class AvatarHTTP(http.BoxFixture):
    stop=http.HTTP시험.stop
    request=http.HTTP시험.request
    login=http.HTTP시험.login
    def setUp(self):
        import threading
        super().setUp()
        self.server=http.admin.Server(self.box,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start();self.addCleanup(self.stop)

    def test_avatar_auth_cache_origin_path(self):
        cookie,_=self.login();h={'Cookie':cookie}
        e=self.box.workspace().people.save('employees',{'name':'시험 얼굴','role':'검토'})['id']
        path='/api/workspace/people/avatar'
        self.assertEqual(self.request('POST',path,{'employee_id':e,'expected':'','image':photo()})[0],401)
        status,_,a=self.request('POST',path,{'employee_id':e,'expected':'','image':photo()},h);self.assertEqual(status,200,a)
        url=path+'/'+e+'/'+a['revision']
        self.assertEqual(self.request('GET',url)[0],401)
        status,headers,raw=self.request('GET',url,headers=h);self.assertEqual(status,200)
        self.assertEqual(headers['Content-Type'],'image/jpeg');self.assertEqual(headers['Cache-Control'],'no-store');self.assertEqual(headers['X-Content-Type-Options'],'nosniff')
        self.assertEqual(self.request('POST',path,{'employee_id':e,'expected':a['revision']},{**h,'Origin':'https://evil.example'})[0],403)
        self.assertNotEqual(self.request('GET',path+'/../../config.yaml',headers=h)[0],200)
