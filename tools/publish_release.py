"""검증된 Box 배포를 불변 파일로 게시하고 v2 최신 포인터를 마지막에 교체한다."""
import argparse,hashlib,json,os,shutil,urllib.request
from pathlib import Path

def publish(stage,server,base):
    manifests=list(stage.glob('release-*.json'))
    if len(manifests)!=1:raise ValueError('배포 manifest는 하나여야 합니다')
    manifest=manifests[0];r=json.loads(manifest.read_text());version=r['version']
    if not all(p.isdecimal() for p in version.split('.')):raise ValueError('버전 형식')
    archive=stage/r['archive']
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=r['archive_sha256']:raise ValueError('묶음 해시 불일치')
    source=Path(__file__).with_name('update.py');updater='updater-'+version+'.py'
    artifacts={manifest.name:manifest.read_bytes(),archive.name:archive.read_bytes(),updater:source.read_bytes()}
    import zipfile,io
    with zipfile.ZipFile(io.BytesIO(artifacts[archive.name])) as z:
        if z.read('cli/tools/update.py')!=artifacts[updater]:raise ValueError('빌드 이후 updater 변경')
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
    # 최초 설치도 검증한 새 updater를 사용한다. 기존 updater .4 고정 bootstrap을 갱신한다.
    script=(server/'install-updater.sh').read_text()
    import re
    script=re.sub(r'updater-[0-9.]+\.py',updater,script)
    script=re.sub(r"'[a-f0-9]{64}'",repr(hashlib.sha256(source.read_bytes()).hexdigest()),script)
    for name,data in [('latest-v2.json',manifest.read_bytes()),('install-updater.sh',script.encode())]:
        temp=server/(name+'.publish-tmp');temp.write_bytes(data);os.replace(temp,server/name)
    print('배포 완료:',version,'리서치',r['research_version'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--stage',type=Path,required=True);p.add_argument('--server',type=Path,required=True);p.add_argument('--base',required=True)
    a=p.parse_args();publish(a.stage,a.server,a.base)
