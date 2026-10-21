"""검증된 Box 배포를 불변 파일로 게시하고 v2 최신 포인터를 마지막에 교체한다."""
import argparse,hashlib,importlib.util,io,json,os,re,urllib.request,zipfile
from pathlib import Path

SOURCE=Path(__file__).with_name('update.py')
spec=importlib.util.spec_from_file_location('publish_updater',SOURCE);tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)

def publish(stage,server,base,stamped_feed=None):
    # stamped_feed differs from base only for a domain move: the release is served from the old host but
    # stamped with the new feed, so boxes switch hosts on their next update.
    manifests=list(stage.glob('release-*.json'))
    if len(manifests)!=1:raise ValueError('배포 manifest는 하나여야 합니다')
    manifest=manifests[0];r=json.loads(manifest.read_text());version=r['version']
    if not all(p.isdecimal() for p in version.split('.')):raise ValueError('버전 형식')
    archive=stage/r['archive']
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=r['archive_sha256']:raise ValueError('묶음 해시 불일치')
    updater='updater-'+version+'.py'
    artifacts={manifest.name:manifest.read_bytes(),archive.name:archive.read_bytes()}
    # The published updater is the feed-stamped copy shipped in the archive, not the plain repo source.
    with zipfile.ZipFile(io.BytesIO(artifacts[archive.name])) as z:body=z.read(tool.UPDATER_KEY)
    if tool.unstamp(body)!=SOURCE.read_bytes():raise ValueError('빌드 이후 updater 변경')
    feed=stamped_feed or base.rstrip('/')+'/latest-v2.json'
    if not tool.valid_feed(feed) or tool.feed_of(body)!=feed:raise ValueError('updater에 기록된 업데이트 주소가 예상 주소와 다릅니다: '+feed)
    if [f['sha256'] for f in r['files'] if f['area']+'/'+f['path']==tool.UPDATER_KEY]!=[hashlib.sha256(body).hexdigest()]:raise ValueError('manifest의 updater 해시 불일치')
    artifacts[updater]=body
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

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--stage',type=Path,required=True);p.add_argument('--server',type=Path,required=True);p.add_argument('--base',required=True)
    p.add_argument('--stamped-feed',help='feed URL the updater must carry (default: --base/latest-v2.json; set only for a domain move)')
    a=p.parse_args(argv);publish(a.stage,a.server,a.base,a.stamped_feed)

if __name__=='__main__':main()
