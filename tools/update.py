"""배포된 코드만 갱신한다. 운영 데이터·비밀·사용자 설정은 갱신하지 않는다."""
import argparse
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
import tempfile
import urllib.request
import urllib.parse
import zipfile
from datetime import datetime, timezone

# Release builds stamp the feed URL into this line (tools/build_release.py). Source checkouts keep it empty.
FEED=''
LIMIT=80*1024*1024
FEED_LINE=re.compile(rb"^FEED='([^'\\\r\n]*)'[ \t]*$",re.M)
UPDATER_KEY='cli/tools/update.py'
NO_FEED='업데이트 주소가 아직 설정되지 않았습니다. 설치를 도와드린 담당자에게 받은 주소로 `ilson update --feed <주소>`를 한 번 실행하세요.'
class MissingFeed(ValueError):pass

def digest(data):return hashlib.sha256(data).hexdigest()
def read(path):return json.loads(path.read_text())
def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)
def save(path,value):atomic(path,json.dumps(value,ensure_ascii=False,indent=2).encode())
def fetch(url):
    if urllib.parse.urlsplit(url).scheme!='https':raise ValueError('HTTPS 배포 주소가 필요합니다')
    with urllib.request.urlopen(url,timeout=45) as r:
        if urllib.parse.urlsplit(r.url).scheme!='https':raise ValueError('HTTPS 연결이 필요합니다')
        data=r.read(LIMIT+1)
        if len(data)>LIMIT:raise ValueError('배포 파일 크기 초과')
        return data

# The same rule as valid_feed in install.sh (tests/test_update_feed.py runs one case list through both):
# lowercase https, a host, optional port 1-65535, no userinfo, and only these printable ASCII characters.
FEED_CHARS=frozenset('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~%/:?=&,;!*()+-')
FEED_FORM=re.compile(r'https://[A-Za-z0-9][A-Za-z0-9.-]*(?::([0-9]{1,5}))?(?:/.*)?\Z',re.S)
def valid_feed(url):
    # The value is stamped into Python source and saved on the box.
    if not isinstance(url,str) or not url or any(c not in FEED_CHARS for c in url):return False
    form=FEED_FORM.match(url)
    return bool(form) and (form.group(1) is None or 1<=int(form.group(1))<=65535)
def feed_of(source):
    # A carriage return lets Python see a line the FEED pattern cannot; refuse such sources outright.
    if b'\r' in source:raise ValueError('업데이트 도구에 CR 문자가 있습니다')
    found=FEED_LINE.findall(source)
    if len(found)!=1:raise ValueError('업데이트 도구의 FEED 줄은 하나여야 합니다')
    return found[0].decode()
def stamp_feed(source,url):
    if not valid_feed(url):raise ValueError('업데이트 주소는 https 주소여야 합니다')
    if b'\r' in source:raise ValueError('업데이트 도구에 CR 문자가 있습니다')
    result,count=re.subn(rb"^FEED=''[ \t]*$",lambda m:b"FEED='"+url.encode()+b"'",source,flags=re.M)
    if count!=1 or len(FEED_LINE.findall(result))!=1:raise ValueError("업데이트 도구에 FEED='' 줄이 정확히 하나 있어야 합니다")
    return result
def unstamp(source):return FEED_LINE.sub(b"FEED=''",source)

def resolve_feed(home,explicit=None):
    # Order: --feed, ILSON_UPDATE_FEED, the release-stamped FEED, then the address this box remembered.
    for name,url in (('--feed',explicit),('ILSON_UPDATE_FEED',os.environ.get('ILSON_UPDATE_FEED') or None),('FEED',FEED or None)):
        if url is None:continue
        if not valid_feed(url):raise ValueError(name+' 업데이트 주소는 https 주소여야 합니다')
        return url
    path=Path(home)/'.updates/feed'
    if path.parent.is_symlink() or path.is_symlink():raise ValueError('업데이트 주소 파일의 링크는 허용하지 않습니다')
    if not path.exists():raise MissingFeed(NO_FEED)
    if not path.is_file():raise ValueError('업데이트 주소 파일을 확인하세요: '+str(path))
    with path.open('rb') as stream:data=stream.read(4097)
    try:url=data.decode().strip() if len(data)<=4096 else None
    except UnicodeDecodeError:url=None
    if url=='':raise MissingFeed(NO_FEED)
    if not valid_feed(url):raise ValueError('저장된 업데이트 주소가 올바르지 않습니다. '+NO_FEED)
    return url

def remember_feed(home,url):
    store=Path(home)/'.updates';path=store/'feed'
    if not valid_feed(url):raise ValueError('업데이트 주소는 https 주소여야 합니다')
    if store.is_symlink() or path.is_symlink():raise ValueError('업데이트 주소 파일의 링크는 허용하지 않습니다')
    data=(url+'\n').encode()
    if path.is_file() and path.read_bytes()==data:return
    atomic(path,data)

def same_updater(current,expected,release,home):
    # A CLI reinstalled from source has FEED='' and never matches a release-stamped hash. Only the FEED line may differ:
    # accept the verified release's own code, or an owned hash after re-stamping the plain bytes with each known feed.
    try:plain=unstamp(current);feeds={feed_of(release),feed_of(current)}
    except ValueError:return False
    if plain==unstamp(release):return True
    saved=Path(home)/'.updates/feed'
    if saved.is_file() and not saved.is_symlink():
        try:feeds.add(saved.read_text().strip())
        except (OSError,ValueError):pass
    if digest(plain) in expected:return True
    for url in feeds:
        if not valid_feed(url):continue
        try:
            if digest(stamp_feed(plain,url)) in expected:return True
        except ValueError:pass
    return False

def allowed(area,name):
    p=PurePosixPath(name)
    if not name or p.is_absolute() or any(x in ('.','..','') for x in name.split('/')) or '\\' in name:return False
    if any(x in ('state','vault','logs','.env','pairing.json','settings.json','settings.local.json','job-settings.json','jobs.conf') or x.startswith('.env') for x in p.parts):return False
    if area=='cli':
        if name.startswith('template/web/') and p.suffix in ('.html','.css','.js','.svg','.woff2','.txt','.json'):return True
        if name in ('template/open.command','template/lib/job-rules.md'):return True
        return name in ('ilson','tools/update.py') or name.startswith('template/lib/') and p.suffix in ('.sh','.py','.js') or name=='template/CLAUDE.md' or name.startswith(('template/claude/commands/','template/claude/skills/')) and p.suffix=='.md'
    if area=='box':
        if name.startswith('web/') and p.suffix in ('.html','.css','.js','.svg','.woff2','.txt','.json'):return True
        if name in ('일손 열기.command','lib/job-rules.md'):return True
        return name=='CLAUDE.md' or name.startswith('lib/') and len(p.parts)==2 and p.suffix in ('.sh','.py','.js') or name.startswith(('lib/research/','lib/social/')) and len(p.parts)==3 and p.suffix=='.py' or name.startswith(('.claude/commands/','.claude/skills/')) and p.suffix=='.md' or name.startswith('packs/research/') and len(p.parts)>=4 and p.suffix in ('.py','.js','.css','.html','.json','.sh','.txt')
    return False

def destination(roots,item):
    if not allowed(item['area'],item['path']):raise ValueError('코드 외 경로는 업데이트할 수 없습니다: '+item['path'])
    root=roots[item['area']];target=root/item['path']
    for parent in [target,*target.parents]:
        if parent==root:break
        if parent.is_symlink():raise ValueError('심볼릭 링크 경로는 덮어쓰지 않습니다: '+item['path'])
    if target.exists() and not target.is_file():raise ValueError('파일이 아닌 대상: '+item['path'])
    return target

def package(manifest,archive):
    if manifest.get('schema')!=1 or digest(archive)!=manifest['archive_sha256']:raise ValueError('배포 묶음 검증 실패')
    result={};seen=set()
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        if len(z.infolist())!=len(manifest['files']) or sum(i.file_size for i in z.infolist())>LIMIT:raise ValueError('배포 파일 목록/크기 불일치')
        for item in manifest['files']:
            key=item['area']+'/'+item['path']
            if key in seen or not allowed(item['area'],item['path']):raise ValueError('허용하지 않는 배포 경로')
            seen.add(key)
            info=z.getinfo(key)
            if (info.external_attr>>16)&0o170000==0o120000:raise ValueError('배포 묶음의 링크는 허용하지 않습니다')
            data=z.read(key)
            if digest(data)!=item['sha256']:raise ValueError('파일 검증 실패: '+key)
            if item['path'].endswith('.py'):compile(data,key,'exec')
            result[key]=data
    return result

def rollback(roots,storage,journal,force_recovery=False):
    if force_recovery:
        return restore_previous(roots,storage,journal,True)
    # 이전 실행기는 새 직원 배정 맥락을 이해하지 못할 수 있다. 대기/실행을 모두 마친 뒤 코드만 복구한다.
    with runtime_lock(roots['box']):
        ensure_idle(roots['box'])
        return restore_previous(roots,storage,journal,False)

def restore_previous(roots,storage,journal,force_recovery=False):
    changes=journal['changes']
    # 새 버전을 사용한 뒤 사람이 수정한 파일은 롤백도 덮어쓰지 않는다.
    for item in changes:
        dest=destination(roots,item)
        actual=digest(dest.read_bytes()) if dest.exists() else None
        if actual not in (item['new_sha256'],item['old_sha256']):raise ValueError('롤백 대상이 변경되었습니다: '+item['path'])
    for item in reversed(changes):
        dest=destination(roots,item)
        if item['backup'] is None:
            if dest.exists():dest.unlink()
        else:
            body=(storage/item['backup']).read_bytes()
            if digest(body)!=item['old_sha256']:raise ValueError('백업 검증 실패')
            atomic(dest,body);dest.chmod(item['old_mode'])
    if journal['previous'] is None:
        (storage/'installed.json').unlink(missing_ok=True)
    else:save(storage/'installed.json',journal['previous'])
    journal['status']='recovered' if force_recovery else 'rolled_back';save(storage/'journal.json',journal)
    print('이전 코드로 복구했습니다. 운영 데이터는 변경하지 않았습니다.')

def apply(roots,manifest,archive,check=False):
    storage=roots['box']/'.updates';storage.mkdir(parents=True,exist_ok=True)
    for p in [storage,*storage.rglob('*')]:
        if p.is_symlink():raise ValueError('업데이트 관리 경로의 링크는 허용하지 않습니다')
    with (storage/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (storage/'journal.json').exists() and read(storage/'journal.json')['status']=='applying':
            if check:raise ValueError('중단된 업데이트가 있습니다. ilson update 로 복구하세요')
            rollback(roots,storage,read(storage/'journal.json'),True)
        bodies=package(manifest,archive)
        previous=read(storage/'installed.json') if (storage/'installed.json').exists() else None
        def release_number(value):
            parts=value.split('.')
            if not parts or any(not p.isdecimal() for p in parts):raise ValueError('배포 버전 형식 오류')
            return tuple(map(int,parts))
        if previous and release_number(manifest['version']) < release_number(previous['version']):
            raise ValueError('이전 버전 자동 적용을 거부합니다. 복구는 --rollback 을 사용하세요')
        release_number(manifest['version'])
        owned=(previous or {}).get('files',{})
        changes=[];preserved=set()
        for item in manifest['files']:
            target=destination(roots,item);key=item['area']+'/'+item['path']
            actual=digest(target.read_bytes()) if target.exists() else None
            if actual==item['sha256']:continue
            if actual is not None and actual in item.get('preserve_sha256',[]):
                preserved.add(key)
                print('기존 확장 기능 보존:',key)
                continue
            expected=[owned[key]] if key in owned else item.get('previous_sha256',[])
            if not isinstance(expected,list):expected=[expected]
            if actual is not None and actual not in expected and not (key==UPDATER_KEY and same_updater(target.read_bytes(),expected,bodies[key],roots['box'])):
                raise ValueError('사용자가 변경했거나 출처가 다른 파일을 보존합니다: '+key)
            changes.append((item,target,key))
        print('배포 버전:',manifest['version'],'· 변경 코드:',len(changes),'개')
        if check:return
        if not changes and previous and previous['version']==manifest['version']:
            print('이미 최신 배포 버전입니다.');return
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        records=[]
        for i,(item,target,key) in enumerate(changes):
            old=target.read_bytes() if target.exists() else None
            backup='backups/'+stamp+'/'+str(i) if old is not None else None
            if backup:atomic(storage/backup,old)
            records.append(dict(area=item['area'],path=item['path'],backup=backup,old_sha256=digest(old) if old is not None else None,
                                new_sha256=item['sha256'],old_mode=target.stat().st_mode&0o777 if old is not None else None))
        journal={'status':'applying','version':manifest['version'],'changes':records,'previous':previous}
        save(storage/'journal.json',journal)
        try:
            for item,target,key in changes:
                atomic(target,bodies[key]);target.chmod(0o755 if item['path']=='ilson' or target.suffix in ('.sh','.command') else 0o644)
            save(storage/'installed.json',{'version':manifest['version'],'files':dict(owned,**{i['area']+'/'+i['path']:i['sha256'] for i in manifest['files'] if i['area']+'/'+i['path'] not in preserved}),
                                          'research_version':manifest.get('research_version'),'installed_at':stamp})
            journal['status']='applied';save(storage/'journal.json',journal)
            save(storage/'history'/('applied-'+stamp+'.json'),journal)
        except BaseException:
            rollback(roots,storage,journal,True);raise
        print('배포 코드 설치 완료.')


def ensure_idle(home):
    db=home/'.workspace/work.sqlite3'
    if not db.exists():return
    if db.is_symlink():raise ValueError('업무 장부 링크는 허용하지 않습니다')
    with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=2) as conn:
        if conn.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0] or conn.execute("SELECT count(*) FROM posts WHERE status='publishing'").fetchone()[0]:
            raise ValueError('실행 또는 대기 중인 업무가 있습니다. 완료 후 ilson update를 다시 실행하세요')


@contextmanager
def runtime_lock(home):
    store=home/'.updates';store.mkdir(exist_ok=True)
    path=store/'runtime.lock'
    if store.is_symlink() or path.is_symlink():raise ValueError('업데이트 잠금 경로를 확인하세요')
    with path.open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('실행 중인 관리자 요청·업무가 있습니다. 완료 후 다시 업데이트하세요') from None
        yield



def ensure_runtime(home,manifest):
    required=manifest.get('runtime_requires',[])
    if not required:return
    # 배포 manifest는 임의 셸 명령이 될 수 없다. 지원하는 영상 입력 의존성만 설치한다.
    if required!=['Pillow>=10.4,<12','pillow-heif>=0.18,<2']:raise ValueError('지원하지 않는 실행 환경 요구사항')
    runtime=home/'.runtime';python=runtime/'venv/bin/python';record=runtime/'requirements.json'
    if runtime.is_symlink() or (runtime/'venv').is_symlink():raise ValueError('실행 환경 경로를 확인하세요')
    if record.is_file() and read(record)==required and python.is_file():
        if subprocess.run([str(python),'-c','import PIL,pillow_heif'],capture_output=True).returncode==0:return
    print('이미지 첨부 실행 환경을 준비합니다. 운영 자료와 시스템 Python은 변경하지 않습니다.',flush=True)
    runtime.mkdir(exist_ok=True)
    if not python.exists():
        result=subprocess.run([sys.executable,'-m','venv',str(runtime/'venv')],capture_output=True,timeout=60)
        if result.returncode:raise ValueError('전용 Python 환경 생성 실패. 기존 버전은 유지됩니다')
    result=subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check',*required],capture_output=True,timeout=240)
    if result.returncode:raise ValueError('이미지 실행 환경 설치 실패. 네트워크·Python 버전을 확인하세요')
    save(record,required)

def ensure_pack_runtime(home):
    # 사용자가 꽂은 팩만 준비한다. 구버전의 실패한 설치 요청도 재시도 대상으로 읽는다.
    wanted=(home/'.runtime/motion').exists()
    db=home/'.workspace/work.sqlite3'
    if not wanted and db.is_file():
        with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as connection:
            wanted=connection.execute("SELECT 1 FROM jobs WHERE kind='motion_install' LIMIT 1").fetchone() is not None
    module=home/'lib/motion_pack.py'
    if not wanted or not module.is_file():return
    if (home/'state/sandbox').exists():raise ValueError('샌드박스에서는 팩 실행 프로그램을 설치하지 않습니다')
    python=home/'.runtime/venv/bin/python'
    result=subprocess.run([str(python) if python.is_file() else sys.executable,str(module),str(home)])
    if result.returncode:raise ValueError('모션그래픽 프로그램 준비 미완료. 위 항목을 확인하고 ilson update를 다시 실행하세요')


def activate_command(home,command):
    python=home/'.runtime/venv/bin/python'
    result=subprocess.run([str(python) if python.is_file() else sys.executable,str(home/'lib/web-admin.py'),command,'--home',str(home)],capture_output=True,text=True,timeout=35)
    if result.returncode:raise ValueError('관리자 '+command+' 미완료. ilson admin status로 상태를 확인하세요')


def apply_running(roots,manifest,archive,check=False):
    # 먼저 파일 충돌·묶음 검증을 마친다. 충돌만으로 실행 중인 관리자를 중지하지 않는다.
    apply(roots,manifest,archive,check=True)
    if check:return
    ensure_runtime(roots['box'],manifest)
    home=roots['box'];state=home/'.updates/installed.json';activation=home/'.updates/activation.json'
    before=read(state) if state.exists() else {}
    pending=read(activation) if activation.exists() else {}
    if before.get('version')==manifest['version'] and pending.get('version')==manifest['version'] and pending.get('status')=='active':
        with runtime_lock(home):
            ensure_idle(home)
            ensure_pack_runtime(home)
        print('관리자와 선택한 팩의 실행 프로그램까지 최신 배포 상태입니다.');return
    with runtime_lock(home):
        ensure_idle(home)
        enabled=(home/'state/web-admin/enabled').is_file() or pending.get('status')=='pending'
        if enabled:
            save(activation,dict(version=manifest['version'],status='pending'))
            activate_command(home,'stop')
        try:
            apply(roots,manifest,archive)
        except BaseException:
            if enabled:
                activate_command(home,'install')
                save(activation,dict(version=before.get('version'),status='active'))
            raise
        save(activation,dict(version=manifest['version'],status='pending' if enabled else 'installed'))
        if enabled:
            activate_command(home,'install')
            save(activation,dict(version=manifest['version'],status='active'))
            print('일손 관리자에 최신 배포를 적용했습니다. 열어 둔 화면을 새로고침하세요.')
        else:print('설치 완료. ilson open으로 최신 관리자를 열 수 있습니다.')
        ensure_pack_runtime(home)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--home',type=Path,default=Path(os.environ.get('ILSON_HOME',str(Path.home()/'ilson'))))
    parser.add_argument('--cli',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--check',action='store_true');parser.add_argument('--rollback',action='store_true')
    parser.add_argument('--feed',default=None)
    parser.add_argument('--manifest',type=Path);parser.add_argument('--archive',type=Path)
    args=parser.parse_args();roots={'box':args.home.resolve(),'cli':args.cli.resolve()}
    if roots['box']==roots['cli'] or roots['cli'].is_relative_to(roots['box']) or roots['box'].is_relative_to(roots['cli']):raise ValueError('CLI와 운영 폴더를 분리해야 합니다')
    if not (roots['box']/'lib/common.sh').is_file() or not (roots['cli']/'ilson').is_file():raise ValueError('기존 일손 설치를 확인하세요')
    if args.rollback:
        storage=roots['box']/'.updates'
        with (storage/'lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            journal=read(storage/'journal.json')
            if journal['status']!='applied':raise ValueError('되돌릴 업데이트가 없습니다')
            rollback(roots,storage,journal)
        return
    if args.manifest:
        manifest=read(args.manifest);archive=args.archive.read_bytes()
    else:
        try:feed=resolve_feed(roots['box'],args.feed)
        except MissingFeed as exc:
            # The scheduled job (lib/update.sh) sets this so a box without an address skips quietly.
            if os.environ.get('ILSON_UPDATE_SKIP_IF_NO_FEED')=='1':print('업데이트 주소가 없어 자동 업데이트를 건너뜁니다.');return
            print(exc,file=sys.stderr);raise SystemExit(1)
        manifest=json.loads(fetch(feed));url=urllib.parse.urljoin(feed,manifest['archive'])
        if urllib.parse.urlsplit(url).netloc!=urllib.parse.urlsplit(feed).netloc:raise ValueError('배포 서버가 다른 묶음입니다')
        archive=fetch(url)
    apply_running(roots,manifest,archive,args.check)
    # Remember the feed only after a real run finished (applied or already latest), so a CLI reinstalled with FEED='' keeps updating.
    if not args.manifest and not args.check:remember_feed(roots['box'],feed)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('업데이트하지 못했습니다:',str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
        raise SystemExit(1)
