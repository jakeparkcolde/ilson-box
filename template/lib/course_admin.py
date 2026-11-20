"""On-demand course admin. No launchd, services, scheduler, or browser automation."""
from __future__ import annotations
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import time
import ilson_platform as platform

SERVICE='ilson-box-admin'
SECRET=re.compile(r'[A-Za-z0-9_-]{32,128}\Z')
DEFAULT_PORT=18794
IDLE_SECONDS=7200
LIBRARY=Path(__file__).resolve().parent


class CourseAdminError(ValueError):
    pass


# Start-failure classes shared with web-admin-server.py (its exit codes). Fixed text only.
EXIT_PERMISSION,EXIT_PORT,EXIT_SETTINGS,EXIT_ELEVATED=3,4,5,6
PERMISSION_MESSAGE='관리자 상태 파일의 소유자·권한이 맞지 않아 관리 화면을 열지 못했습니다.'
PORT_MESSAGE='관리 화면 포트를 열지 못했습니다. 포트를 쓰는 다른 프로그램을 종료하거나 잠시 뒤 다시 시도해주세요.'
SETTINGS_MESSAGE='관리자 연결 설정이 없거나 형식이 다릅니다. ilson open을 다시 실행해주세요.'


def permission_message(elevated):
    return PERMISSION_MESSAGE+' '+(platform.elevated_hint() if elevated else 'ilson doctor로 확인해주세요.')


def child_failure(code):
    if code==EXIT_PORT: return PORT_MESSAGE
    if code==EXIT_SETTINGS: return SETTINGS_MESSAGE
    if code in (EXIT_PERMISSION,EXIT_ELEVATED): return permission_message(code==EXIT_ELEVATED)
    return '관리 웹을 시작하지 못했습니다. ilson doctor로 확인하세요.'


def private_home(home):
    home=platform.safe_path(home)
    forbidden=[Path.home()/'Documents']
    forbidden.extend(Path(os.environ[key]) for key in ('OneDrive','OneDriveConsumer','OneDriveCommercial') if os.environ.get(key))
    for path in forbidden:
        try: home.resolve().relative_to(path.resolve())
        except ValueError: continue
        raise CourseAdminError('관리자 상태는 Documents·OneDrive 밖의 개인 폴더에 보관하세요.')
    platform.safe_path(home/'state')
    private=platform.private_dir(home/'state/web-admin')
    return home,private


def read(private,name):
    try: return platform.files(private).text(name,65536,private=True)[0]
    except FileNotFoundError: return None


def record(private):
    raw=read(private,'server.json')
    if raw is None: return None
    try:
        value=json.loads(raw)
        if (value.get('service')!=SERVICE or type(value.get('pid')) is not int or value['pid']<=0 or
                type(value.get('port')) is not int or not 1<=value['port']<=65535 or
                not isinstance(value.get('instance'),str) or not SECRET.fullmatch(value['instance']) or
                not isinstance(value.get('executable'),str) or not isinstance(value.get('started_at'),(int,float)) or
                not re.fullmatch('[a-f0-9]{64}',value.get('source_digest',''))): raise ValueError()
        return value
    except (ValueError,TypeError,AttributeError):
        raise CourseAdminError('관리자 실행 기록을 확인하세요. 기존 기록을 보존했습니다.') from None


def request(port,path,*,body=None,cookie=None):
    connection=HTTPConnection('127.0.0.1',port,timeout=1)
    try:
        headers={}
        if cookie: headers['Cookie']=cookie
        raw=None
        if body is not None:
            headers.update({'Origin':f'http://127.0.0.1:{port}','Content-Type':'application/json'})
            raw=json.dumps(body).encode()
        connection.request('POST' if body is not None else 'GET',path,body=raw,headers=headers)
        response=connection.getresponse();raw=response.read(8193)
        if len(raw)>8192 or response.status!=200: raise CourseAdminError('관리자 응답을 확인하지 못했습니다.')
        return json.loads(raw),response.getheader('Set-Cookie')
    finally: connection.close()


def health(info):
    if info is None: return False
    try: data,_=request(info['port'],'/api/health')
    except (OSError,ValueError): return False
    return (data.get('service')==SERVICE and data.get('instance')==info['instance'] and data.get('pid')==info['pid'])


def locked(private):
    try: fd=platform.acquire_lock(private/'server.lock')
    except BlockingIOError: return True
    os.close(fd);return False


def prepare(private):
    for name,length in (('token',32),('instance',24)):
        try: value=read(private,name)
        except platform.AccessProblem:
            # Windows: private_dir() already repaired what this window may repair. A value that
            # still fails its check is never used; with no server running it is replaced by a
            # fresh one in this user's name (the folder is ours, so the replace is allowed).
            if not platform.IS_WINDOWS or locked(private): raise
            value=None
        if value is None: platform.atomic_write(private/name,secrets.token_urlsafe(length).encode())
        elif not SECRET.fullmatch(value): raise CourseAdminError('관리자 연결 설정을 확인하세요. 기존 값을 보존했습니다.')


def authenticate(private,info):
    if not health(info): raise CourseAdminError('응답 없는 관리 화면이 있습니다. ilson admin status로 확인하세요.')
    token=read(private,'token')
    if not token or not SECRET.fullmatch(token): raise CourseAdminError('관리자 연결 설정을 확인하세요.')
    _,cookie=request(info['port'],'/api/session',body={'token':token})
    if not cookie: raise CourseAdminError('관리자 인증을 확인하지 못했습니다.')
    return cookie.split(';',1)[0]


def wait_stopped(private,*,wait=5):
    deadline=time.monotonic()+wait
    while locked(private):
        if time.monotonic()>=deadline: raise CourseAdminError('관리자 중지를 확인하지 못했습니다.')
        time.sleep(.05)


def stop(home,*,force=False):
    home,private=private_home(home)
    info=record(private)
    if not locked(private):
        print('관리 웹이 실행 중이 아닙니다.');return 0
    if health(info):
        cookie=authenticate(private,info)
        request(info['port'],'/api/admin/shutdown',body={},cookie=cookie)
    elif force and info:
        executable,started=platform.process_identity(info['pid'])
        if os.path.normcase(executable)!=os.path.normcase(str(Path(info['executable']).resolve())) or abs(started-info['started_at'])>1:
            raise CourseAdminError('기록된 관리자 프로세스와 다릅니다. 종료하지 않았습니다.')
        os.kill(info['pid'],signal.SIGTERM)
    else: raise CourseAdminError('응답 없는 관리 화면이 있습니다. ilson admin stop --force로 기록된 PID를 확인해 중지하세요.')
    wait_stopped(private)
    print('관리 웹을 중지했습니다. 다시 열 때는 ilson open을 실행하세요.');return 0


def status(home):
    home,private=private_home(home);info=record(private)
    if info and locked(private) and health(info):
        print(f"관리 웹이 실행 중입니다. 주소: http://127.0.0.1:{info['port']}/");return 0
    print('관리 웹이 응답하지 않습니다. ilson open으로 다시 시작하세요.');return 1


def start(home,vault,*,port=None,wait=12,idle_seconds=IDLE_SECONDS):
    home,private=private_home(home)
    vault=platform.safe_path(vault)
    if not vault.is_dir(): raise CourseAdminError('실습 볼트가 없습니다. 강의판 설치 상태를 확인하세요.')
    try: launcher=platform.acquire_lock(private/'launcher.lock')
    except BlockingIOError: raise CourseAdminError('다른 창에서 관리 웹을 준비하고 있습니다. 잠시 뒤 다시 시도하세요.') from None
    install=None
    try:
        # Installer and startup share the code lock; installer then checks server.lock.
        install=platform.acquire_lock(LIBRARY/'.install.lock')
        prepare(private);info=record(private);digest=platform.code_digest(LIBRARY)
        if locked(private):
            if not health(info): raise CourseAdminError('응답 없는 관리 화면이 있습니다. ilson admin stop으로 먼저 확인하세요.')
            if info['source_digest']==digest: return info['port']
            stop(home);info=None
        preferred=port
        if preferred is None:
            raw=read(private,'config.json')
            if raw is not None:
                try:
                    config=json.loads(raw)
                    if config.get('version')!=1 or type(config.get('port')) is not int: raise ValueError()
                    preferred=config['port']
                except (ValueError,TypeError,AttributeError): raise CourseAdminError('관리자 포트 설정을 확인하세요.') from None
        preferred=DEFAULT_PORT if preferred is None else preferred
        if type(preferred) is not int or not 1024<=preferred<=65535: raise CourseAdminError('관리자 포트는 1024~65535로 지정하세요.')
        args=[sys.executable,'-X','utf8',str(LIBRARY/'web-admin-server.py'),'--home',str(home),'--vault',str(vault),
              '--profile','course','--port',str(preferred),'--idle-seconds',str(idle_seconds)]
        flags={'creationflags':getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0)} if platform.IS_WINDOWS else {'start_new_session':True}
        logs=[]
        try:
            for name in ('stdout.log','stderr.log'):
                fd=platform.open_private(private/name,os.O_WRONLY|os.O_APPEND)
                if os.fstat(fd).st_nlink!=1: os.close(fd);raise CourseAdminError('관리자 로그 경로를 확인하세요.')
                logs.append(os.fdopen(fd,'ab'))
            child=subprocess.Popen(args,cwd=home,stdin=subprocess.DEVNULL,stdout=logs[0],stderr=logs[1],
                env=dict(os.environ,ILSON_HOME=str(home),ILSON_PROFILE='course',ILSON_COURSE_VAULT=str(vault)),**flags)
        finally:
            for stream in logs: stream.close()
        deadline=time.monotonic()+wait
        while True:
            current=record(private)
            if current and current['pid']==child.pid and current['source_digest']==digest and locked(private) and health(current): return current['port']
            code=child.poll()
            if code is not None: raise CourseAdminError(child_failure(code))
            if time.monotonic()>=deadline: raise CourseAdminError('관리 웹이 아직 응답하지 않습니다. ilson admin status로 확인하세요.')
            time.sleep(.1)
    finally:
        if install is not None: os.close(install)
        os.close(launcher)


def open_browser(home,port):
    _,private=private_home(home);info=record(private)
    if not info or info['port']!=port or not health(info): raise CourseAdminError('관리자 연결을 확인하지 못했습니다.')
    token=read(private,'token')
    if not token or not SECRET.fullmatch(token): raise CourseAdminError('관리자 연결 설정을 확인하세요.')
    url=f'http://127.0.0.1:{port}/#token={token}'
    if platform.IS_WINDOWS: os.startfile(url)
    else:
        result=subprocess.run(['/usr/bin/open',url],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
        if result.returncode: raise CourseAdminError('관리자는 준비됐지만 브라우저를 열지 못했습니다.')


def main(args):
    try:
        if args.command=='status': return status(args.home)
        if args.command=='stop': return stop(args.home,force=args.force)
        from license import evaluate
        if not evaluate(args.home)[0]: raise CourseAdminError('일손 라이선스가 필요합니다. ilson license activate로 확인하세요.')
        if args.vault is None: raise CourseAdminError('강의 실습 볼트를 지정하세요.')
        port=start(args.home,args.vault,port=args.port)
        if args.command=='open': open_browser(args.home,port)
        print('일손 관리 화면을 열었습니다. 유휴 2시간 뒤 자동 종료됩니다.');return 0
    except CourseAdminError as error:
        print(str(error));return 1
    except platform.AccessProblem as error:
        print(permission_message(error.elevated));return 1
    except PermissionError:
        print(permission_message(False));return 1
    except (OSError,ValueError) as error:
        # license.ElevatedOwnerError (from evaluate) carries no class we import here.
        if str(error)=='ELEVATED_OWNER': print(permission_message(True));return 1
        # Messages are fixed local strings; never include subprocess output or URLs.
        print('관리 화면을 처리하지 못했습니다. ilson admin status 또는 ilson doctor로 확인하세요.');return 1
