"""화이트리스트 코드와 명시적으로 지정한 배포 리서치 팩으로만 릴리스를 조립한다."""
import argparse
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import zipfile

# 2026-10-13: Jake 설치본의 확장 관리자/SNS 코드를 공개 저장소 버전으로 내리지 않는다.
# 정확히 검토한 해시만 보존하며 알 수 없는 수정은 계속 전체 적용을 차단한다.
PRESERVE={}


ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('updater',ROOT/'tools/update.py');updater=importlib.util.module_from_spec(spec);spec.loader.exec_module(updater)

def build(output,version,pack):
    output.mkdir(parents=True,exist_ok=True)
    files=[];members={}
    accepted=json.loads((ROOT/'tools/manager-baseline.json').read_text())
    with zipfile.ZipFile(pack) as z:
        pack_data={i.filename:z.read(i) for i in z.infolist() if not i.is_dir()}
    # 관리자와 독립 실행 팩은 같은 검증된 ZIP에서 조립한다. 예전 사본이 다시 배포되지 않는다.
    overrides={}
    for name,data in pack_data.items():
        if '/' not in name and name.endswith('.py') and name!='serve.py':overrides['template/lib/research/'+name]=data
        if name.startswith('web/'):overrides['template/web/current/pack-library/'+name[4:]]=data

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
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        for key,data in members.items():z.writestr(key,data)
    archive=buf.getvalue();archive_name='ilson-box-'+version+'.zip'
    release={'schema':1,'version':version,'research_version':pv,'runtime_requires':['Pillow>=10.4,<12','pillow-heif>=0.18,<2'],'archive':archive_name,'archive_sha256':updater.digest(archive),'files':files}
    with (output/archive_name).open('xb') as f:f.write(archive)
    with (output/('release-'+version+'.json')).open('x') as f:json.dump(release,f,ensure_ascii=False,indent=2)
    return release
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--version',required=True);p.add_argument('--pack',type=Path,required=True);a=p.parse_args()
    r=build(a.output,a.version,a.pack);print('릴리스:',r['version'],'코드 파일:',len(r['files']))
