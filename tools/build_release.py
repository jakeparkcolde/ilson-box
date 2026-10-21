"""화이트리스트 코드와 명시적으로 지정한 배포 리서치 팩으로만 릴리스를 조립한다."""
import argparse
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('updater',ROOT/'tools/update.py');updater=importlib.util.module_from_spec(spec);spec.loader.exec_module(updater)

def pack_sources():
    # Template files a research pack carries: top-level research modules and every pack-library web file.
    web=ROOT/'template/web/current/pack-library'
    files=[p for p in (ROOT/'template/lib/research').glob('*.py') if p.is_file()]
    files+=[p for p in web.rglob('*') if p.is_file() and not any(part.startswith('.') or part=='__pycache__' for part in p.relative_to(web).parts)]
    return sorted(p.relative_to(ROOT).as_posix() for p in files)

def dirty_files(root=ROOT):
    # Modified or untracked files. A build walks the working tree, and a dirty build leaves the shipped
    # updater's plain version out of the previous_sha256 history, stranding boxes that do not own it yet.
    result=subprocess.run(['git','status','--porcelain','--untracked-files=all'],cwd=root,capture_output=True,text=True)
    if result.returncode:raise ValueError('git 상태를 확인하지 못했습니다')
    return [line for line in result.stdout.splitlines() if line.strip()]

def load_preserve(path):
    # preserve_sha256 lists the exact hashes of owner edits that were reviewed and approved: update.py keeps such a
    # file instead of stopping with a conflict. They live only in published manifests, so each build carries them
    # forward from the previous one. Unknown edits still stop the whole update.
    carried={}
    for item in json.loads(Path(path).read_text())['files']:
        if 'preserve_sha256' not in item:continue
        key=item['area']+'/'+item['path'];values=item['preserve_sha256']
        if key in carried:raise ValueError('이전 manifest에 같은 파일이 두 번 있습니다: '+key)
        if not isinstance(values,list) or not values or not all(isinstance(v,str) and re.fullmatch('[0-9a-f]{64}',v) for v in values):
            raise ValueError('preserve_sha256 값은 64자리 소문자 16진수 목록이어야 합니다: '+key)
        carried[key]=values
    return carried

def carry_preserve(files,carried):
    entries={f['area']+'/'+f['path']:f for f in files}
    for key,values in carried.items():
        entry=entries.get(key)
        if entry is None:print('보존 해시 이월 건너뜀(새 배포에 없는 파일):',key);continue
        if entry['sha256'] in values:raise ValueError('보존 해시가 새 배포 파일의 해시와 같습니다. 이전 manifest를 검토하세요: '+key)
        # Added last, after previous_sha256, like the reviewed 2026.10.16.x manifests.
        entry['preserve_sha256']=list(values)
        print('보존 해시 이월:',key,'('+str(len(values))+'개)')

def build(output,version,pack,feed=None,preserve_from=None):
    # Every box updates from the feed stamped into the shipped updater. An empty feed would strand them all.
    feed=feed or os.environ.get('ILSON_RELEASE_FEED','')
    if not updater.valid_feed(feed):raise ValueError('릴리스 업데이트 주소가 필요합니다: --feed 또는 ILSON_RELEASE_FEED (https://.../latest-v2.json)')
    carried=load_preserve(preserve_from) if preserve_from else {}
    files=[];members={}
    accepted=json.loads((ROOT/'tools/manager-baseline.json').read_text())
    with zipfile.ZipFile(pack) as z:
        pack_data={i.filename:z.read(i) for i in z.infolist() if not i.is_dir()}
    # 관리자와 독립 실행 팩은 같은 검증된 ZIP에서 조립한다. 예전 사본이 다시 배포되지 않는다.
    overrides={}
    for name,data in pack_data.items():
        if '/' not in name and name.endswith('.py') and name!='serve.py':overrides['template/lib/research/'+name]=data
        if name.startswith('web/'):overrides['template/web/current/pack-library/'+name[4:]]=data
    # The pack must be built from the current repo sources (tools/refresh_pack.py), checked both ways.
    # A stale pack would silently revert template fixes on every box; a pack missing a template file would ship
    # an incomplete standalone copy. The 0.16.1 layout matches the template one to one, so there are no exceptions.
    stale=sorted(rel for rel,data in overrides.items() if not (ROOT/rel).is_file() or (ROOT/rel).read_bytes()!=data)
    stale+=sorted(set(pack_sources())-set(overrides))
    if stale:raise ValueError('리서치 팩이 저장소와 다릅니다. 현재 template 파일로 팩을 다시 만드세요: '+', '.join(stale))

    def add(area,name,data,baseline=None):
        if not updater.allowed(area,name):return
        key=area+'/'+name
        if key in members:raise ValueError('중복 파일')
        members[key]=data
        files.append({'area':area,'path':name,'sha256':updater.digest(data),'previous_sha256':updater.digest(baseline) if baseline is not None else None})
        source_name=name if area=='cli' else 'template/'+name
        if source_name in accepted:files[-1]['previous_sha256']=[accepted[source_name]]
    for source in sorted(ROOT.rglob('*')):
        if not source.is_file() or '.git' in source.parts:continue
        rel=source.relative_to(ROOT).as_posix()
        if not updater.allowed('cli',rel):continue
        result=subprocess.run(['git','show','HEAD:'+rel],cwd=ROOT,capture_output=True)
        baseline=result.stdout if result.returncode==0 else None
        history=subprocess.run(['git','log','-20','--format=%H','HEAD','--',rel],cwd=ROOT,capture_output=True,text=True)
        history_hashes=[]
        for revision in history.stdout.splitlines():
            old=subprocess.run(['git','show',revision+':'+rel],cwd=ROOT,capture_output=True)
            if old.returncode==0:history_hashes.append(updater.digest(old.stdout))
        body=overrides.pop(rel,source.read_bytes())
        if rel=='tools/update.py':
            # stamp_feed refuses unless exactly one FEED='' line is replaced. History hashes below stay plain git versions.
            body=updater.stamp_feed(body,feed)
            if updater.feed_of(body)!=feed:raise ValueError('updater 주소 기록 실패')
            compile(body,rel,'exec')
        if rel in accepted:accepted_hash=accepted[rel];accepted_history=[accepted_hash]
        else:accepted_history=[]
        add('cli',rel,body,baseline)
        files[-1]['previous_sha256']=list(dict.fromkeys(history_hashes+accepted_history))
        if rel.startswith('template/lib/') or rel=='template/CLAUDE.md':
            add('box',rel.removeprefix('template/'),body,baseline)
        elif rel.startswith('template/web/'):
            add('box',rel.removeprefix('template/'),body,baseline)
        elif rel=='template/open.command':
            add('box','일손 열기.command',body,baseline)
        elif rel.startswith('template/claude/'):
            add('box','.claude/'+rel.removeprefix('template/claude/'),body,baseline)
        if files[-1]['area']=='box':files[-1]['previous_sha256']=list(dict.fromkeys(history_hashes+accepted_history))
    for rel,body in overrides.items():
        add('cli',rel,body)
        add('box',rel.removeprefix('template/'),body)
    with zipfile.ZipFile(pack) as z:
        manifest=json.loads(z.read('manifest.json'));pv=manifest['version']
        if not pv or any(c not in '0123456789.' for c in pv):raise ValueError('팩 버전 형식')
        for info in z.infolist():
            if info.is_dir() or info.filename=='install.sh':continue
            name='packs/research/'+pv+'/'+info.filename
            if not updater.allowed('box',name):raise ValueError('팩에 코드 외 파일이 있습니다')
            add('box',name,z.read(info))
    if updater.feed_of(members.get(updater.UPDATER_KEY,b''))!=feed:raise ValueError('배포 updater에 업데이트 주소가 없습니다')
    carry_preserve(files,carried)
    # Nothing is written until every check has passed, so a refused build leaves no output folder.
    output.mkdir(parents=True,exist_ok=True)
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        for key,data in members.items():z.writestr(key,data)
    archive=buf.getvalue();archive_name='ilson-box-'+version+'.zip'
    release={'schema':1,'version':version,'research_version':pv,'runtime_requires':['Pillow>=10.4,<12','pillow-heif>=0.18,<2'],'archive':archive_name,'archive_sha256':updater.digest(archive),'files':files}
    with (output/archive_name).open('xb') as f:f.write(archive)
    with (output/('release-'+version+'.json')).open('x') as f:json.dump(release,f,ensure_ascii=False,indent=2)
    return release
def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--version',required=True);p.add_argument('--pack',type=Path,required=True)
    p.add_argument('--feed',help='latest-v2.json URL stamped into the shipped updater (default: ILSON_RELEASE_FEED)')
    p.add_argument('--allow-dirty',action='store_true',help='build from uncommitted changes (rehearsals only, never for a published release)')
    previous=p.add_mutually_exclusive_group()
    previous.add_argument('--preserve-from',type=Path,help='previous release manifest (release-<version>.json) whose preserve_sha256 entries are carried forward')
    previous.add_argument('--no-preserve-from',action='store_true',help='build without carrying preserve_sha256 (first release or rehearsals)');a=p.parse_args(argv)
    if a.preserve_from is None and not a.no_preserve_from:
        raise SystemExit('이전 배포의 검토한 보존 해시를 이어받아야 합니다: --preserve-from <배포 폴더>/release-<이전 버전>.json (이어받을 것이 없을 때만 --no-preserve-from)')
    dirty=dirty_files()
    if dirty and not a.allow_dirty:
        raise SystemExit('커밋하지 않은 변경이 있어 빌드하지 않습니다. 커밋 후 다시 실행하세요(시험 빌드만 --allow-dirty):\n'+'\n'.join(dirty[:20]))
    r=build(a.output,a.version,a.pack,a.feed,preserve_from=a.preserve_from);print('릴리스:',r['version'],'코드 파일:',len(r['files']))

if __name__=='__main__':main()
