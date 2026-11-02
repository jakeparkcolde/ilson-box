"""검증된 Box 배포를 게시한다. 폴더 경로는 불변 파일을 올리고 v2 최신 포인터를 마지막에 교체하고, GitHub 경로는 사전 공개 Release를 만든 뒤 따로 Latest로 올린다."""
import argparse,hashlib,importlib.util,io,json,os,re,subprocess,tempfile,time,urllib.parse,urllib.request,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path(__file__).with_name('update.py')
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module
tool=load('publish_updater',SOURCE)
checker=load('publish_checker',ROOT/'tools/check_public.py')
builder=load('publish_builder',ROOT/'tools/build_release.py')
FEED_ASSET='latest-v2.json'
REPO=re.compile(r'[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9._-]*\Z')

def validate_stage(stage,feed):
    # What both routes need to be true of a stage. Nothing here touches a server.
    manifests=list(stage.glob('release-*.json'))
    if len(manifests)!=1:raise ValueError('배포 manifest는 하나여야 합니다')
    manifest=manifests[0];r=json.loads(manifest.read_text());version=r['version']
    if not all(p.isdecimal() for p in version.split('.')):raise ValueError('버전 형식')
    archive=stage/r['archive']
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=r['archive_sha256']:raise ValueError('묶음 해시 불일치')
    # The published updater is the feed-stamped copy shipped in the archive, not the plain repo source.
    with zipfile.ZipFile(io.BytesIO(archive.read_bytes())) as z:body=z.read(tool.UPDATER_KEY)
    if tool.unstamp(body)!=SOURCE.read_bytes():raise ValueError('빌드 이후 updater 변경')
    if not tool.valid_feed(feed) or tool.feed_of(body)!=feed:raise ValueError('updater에 기록된 업데이트 주소가 예상 주소와 다릅니다: '+feed)
    if [f['sha256'] for f in r['files'] if f['area']+'/'+f['path']==tool.UPDATER_KEY]!=[hashlib.sha256(body).hexdigest()]:raise ValueError('manifest의 updater 해시 불일치')
    return manifest,r,archive,body

def publish(stage,server,base,stamped_feed=None):
    # stamped_feed differs from base only for a domain move: the release is served from the old host but
    # stamped with the new feed, so boxes switch hosts on their next update.
    manifest,r,archive,body=validate_stage(stage,stamped_feed or base.rstrip('/')+'/latest-v2.json')
    version=r['version'];updater='updater-'+version+'.py'
    artifacts={manifest.name:manifest.read_bytes(),archive.name:archive.read_bytes(),updater:body}
    server.mkdir(parents=True,exist_ok=True)
    for name,data in artifacts.items():
        dest=server/name
        if dest.exists():
            if dest.read_bytes()!=data:raise ValueError('이미 발행한 버전은 덮어쓸 수 없습니다: '+name)
        else:
            with dest.open('xb') as f:f.write(data)
        with urllib.request.urlopen(base.rstrip('/')+'/'+name,timeout=40) as response:
            if response.read()!=data:raise ValueError('HTTPS 배포 검증 실패')
    old=json.loads((server/'latest-v2.json').read_text()) if (server/'latest-v2.json').exists() else None
    if old and tuple(map(int,old['version'].split('.')))>tuple(map(int,version.split('.'))):raise ValueError('최신 포인터 다운그레이드 금지')
    # 최초 설치도 검증한 새 updater를 사용한다. bootstrap에는 주소가 기록된 updater의 SHA256을 고정한다.
    script=(server/'install-updater.sh').read_text()
    script=re.sub(r'updater-[0-9.]+\.py',updater,script)
    script=re.sub(r"'[a-f0-9]{64}'",repr(hashlib.sha256(body).hexdigest()),script)
    for name,data in [('latest-v2.json',manifest.read_bytes()),('install-updater.sh',script.encode())]:
        temp=server/(name+'.publish-tmp');temp.write_bytes(data);os.replace(temp,server/name)
    print('배포 완료:',version,'리서치',r['research_version'])

def run_gh(args):
    try:return subprocess.run(['gh',*args],capture_output=True,env=dict(os.environ,GH_PROMPT_DISABLED='1'))
    except FileNotFoundError:raise ValueError('gh 명령을 찾지 못했습니다') from None

def gh_error(result):return result.stderr.decode('utf-8','replace').strip()[:300]

def gh_read(gh,path,missing=('HTTP 404',)):
    # One read-only API call. None means the thing does not exist; every other failure stops the publish.
    result=gh(['api',path])
    if result.returncode==0:return json.loads(result.stdout)
    if any(code in gh_error(result) for code in missing):return None
    raise ValueError('GitHub 확인 실패 ('+path+'): '+gh_error(result))

def github_feed(repo):return 'https://github.com/'+repo+'/releases/latest/download/'+FEED_ASSET

def github_stage(stage,repo):
    if not REPO.match(repo):raise ValueError('--github 값은 OWNER/REPO 형식이어야 합니다: '+repo)
    manifest,r,archive,_=validate_stage(stage,github_feed(repo))
    if r['archive']!='ilson-box-'+r['version']+'.zip':raise ValueError('묶음 파일 이름이 버전과 다릅니다: '+r['archive'])
    return manifest,r,archive,{r['archive']:archive.read_bytes(),FEED_ASSET:manifest.read_bytes()}

def version_of(tag):
    if not re.fullmatch(r'v[0-9]+(\.[0-9]+)*',tag):raise ValueError('릴리스 태그 형식을 읽지 못했습니다: '+tag)
    return tuple(map(int,tag[1:].split('.')))

def head_commit():
    result=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True)
    if result.returncode:raise ValueError('현재 커밋을 확인하지 못했습니다')
    return result.stdout.strip()

def verify_release(repo,tag,release,assets,fetch):
    # Anonymous, the way a box reads it: no gh and no token. A difference here means the release must not be used.
    if sorted(a['name'] for a in release.get('assets',[]))!=sorted(assets):raise ValueError('릴리스의 파일 구성이 다릅니다: '+tag)
    for name,data in assets.items():
        url='https://github.com/'+repo+'/releases/download/'+tag+'/'+name
        try:body=fetch(url)
        except Exception as exc:raise ValueError('공개 다운로드 실패: '+url+' ('+type(exc).__name__+')') from None
        if body!=data:raise ValueError('이미 올린 파일과 스테이징이 다릅니다. 덮어쓰지 않습니다: '+name)

def create_release(stage,repo,gh=run_gh,fetch=tool.fetch,denylist=checker.DEFAULT_DENYLIST,use_denylist=True):
    # Latest does not move here. Boxes keep the current release until promote_release.
    manifest,r,archive,assets=github_stage(stage,repo)
    version=r['version'];tag='v'+version;releases='repos/'+repo+'/releases'
    report=checker.check(archive,manifest,denylist=denylist,use_denylist=use_denylist)
    print('\n'.join(report.lines()))
    if report.blocked:raise ValueError('공개 검사에서 막혀 올리지 않습니다')
    dirty=builder.dirty_files(ROOT)
    if dirty:raise ValueError('커밋하지 않은 변경이 있어 올리지 않습니다:\n'+'\n'.join(dirty[:20]))
    sha=head_commit()
    if gh_read(gh,'repos/'+repo+'/commits/'+sha,('HTTP 404','HTTP 422')) is None:raise ValueError('이 커밋이 GitHub에 없습니다. 먼저 push한 뒤 다시 실행하세요: '+sha)
    latest=gh_read(gh,releases+'/latest')
    if latest and version_of(tag)<=version_of(latest['tag_name']):raise ValueError('새 버전은 현재 Latest보다 커야 합니다: '+latest['tag_name']+' → '+tag)
    release=gh_read(gh,releases+'/tags/'+tag)
    if release is None:
        # gh would attach a release to an existing tag and ignore --target.
        if gh_read(gh,'repos/'+repo+'/git/ref/tags/'+tag) is not None:raise ValueError('릴리스 없이 같은 태그가 이미 있습니다: '+tag)
        with tempfile.TemporaryDirectory() as folder:
            feed=Path(folder)/FEED_ASSET;feed.write_bytes(assets[FEED_ASSET])
            result=gh(['release','create',tag,str(archive),str(feed),'--repo',repo,'--target',sha,'--prerelease','--latest=false',
                       '--title','ilson-box '+version,'--notes','Box '+version+' · research '+str(r['research_version'])])
        if result.returncode:raise ValueError('릴리스를 만들지 못했습니다: '+gh_error(result))
        release={'assets':[{'name':name} for name in assets]}
    verify_release(repo,tag,release,assets,fetch)
    print('사전 공개 완료:',tag,'· Latest는 그대로입니다. 시험 후 Latest로 올리는 명령:')
    print('python3 tools/publish_release.py --stage '+str(stage)+' --github '+repo+' --promote')

def promote_release(stage,repo,gh=run_gh,fetch=tool.fetch,sleep=time.sleep,attempts=6,wait=5):
    manifest,r,archive,assets=github_stage(stage,repo)
    tag='v'+r['version'];releases='repos/'+repo+'/releases'
    release=gh_read(gh,releases+'/tags/'+tag)
    if release is None:raise ValueError('릴리스가 없습니다. 먼저 --promote 없이 올리세요: '+tag)
    verify_release(repo,tag,release,assets,fetch)
    latest=gh_read(gh,releases+'/latest')
    if latest and latest['tag_name']==tag:print('이미 Latest입니다:',tag)
    else:
        if latest and version_of(tag)<version_of(latest['tag_name']):raise ValueError('Latest를 낮은 버전으로 옮기지 않습니다: '+latest['tag_name']+' → '+tag)
        result=gh(['release','edit',tag,'--repo',repo,'--prerelease=false','--latest'])
        if result.returncode:raise ValueError('Latest로 올리지 못했습니다: '+gh_error(result))
    # The two addresses a box reads, joined the way update.py joins them.
    feed=github_feed(repo);urls={feed:assets[FEED_ASSET],urllib.parse.urljoin(feed,r['archive']):assets[r['archive']]}
    for attempt in range(attempts):
        if attempt:sleep(wait)
        try:
            if all(fetch(url)==data for url,data in urls.items()):
                print('Latest 확인 완료:',tag,'리서치',r['research_version']);return
        except Exception:pass
    raise ValueError('Latest 지정 뒤에도 공개 주소가 이 배포를 주지 않습니다. 기기가 받기 전에 확인하세요: '+feed)

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--stage',type=Path,required=True);p.add_argument('--server',type=Path);p.add_argument('--base')
    p.add_argument('--stamped-feed',help='feed URL the updater must carry (default: --base/latest-v2.json; set only for a domain move)')
    p.add_argument('--github',metavar='OWNER/REPO',help='publish as a GitHub prerelease instead of into a folder')
    p.add_argument('--promote',action='store_true',help='with --github: move Latest to the release already uploaded')
    p.add_argument('--denylist',type=Path,help='with --github: client name list for the public check')
    p.add_argument('--no-denylist',action='store_true',help='with --github: run the public check without client names')
    a=p.parse_args(argv)
    if a.github is None:
        if a.promote or a.denylist or a.no_denylist:p.error('--promote, --denylist, --no-denylist 는 --github 와 함께 씁니다')
        if a.server is None or a.base is None:p.error('--server 와 --base, 또는 --github 가 필요합니다')
        publish(a.stage,a.server,a.base,a.stamped_feed);return
    if a.server is not None or a.base is not None or a.stamped_feed:p.error('--github 는 --server, --base, --stamped-feed 와 함께 쓸 수 없습니다')
    if a.denylist and a.no_denylist:p.error('--denylist 와 --no-denylist 는 함께 쓸 수 없습니다')
    if a.promote and (a.denylist or a.no_denylist):p.error('--promote 는 공개 검사를 하지 않습니다')
    try:
        if a.promote:promote_release(a.stage,a.github)
        else:create_release(a.stage,a.github,denylist=a.denylist or checker.DEFAULT_DENYLIST,use_denylist=not a.no_denylist)
    except ValueError as exc:raise SystemExit('게시하지 않았습니다: '+str(exc))

if __name__=='__main__':main()
