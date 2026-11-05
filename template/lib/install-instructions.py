"""Install only unchanged official instructions; preserve user edits."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

# Known source-history SHA-256 values through v2026.11.5.2, including tar.gz installs.
BASELINE = {'CLAUDE.md': ['7270c5b0b39ff26e42f04fd3f4c3bca8cc03d87429c2d36ed97ef56c8c483763', '27b87048e7750e66797732cc896e64254d8bd3a0c77e79e9f66ca6a939d40cce', '08f015ab0cdae621e146a322ca3096aa9b7186bd71f0d6f79f72d317e0da769a', '067b6d79f6e9280a06e366d39aaa969604cf3f7858b7b4c2eb5600884755c645', '78cdb3de98c4820aa801d1c4dfc96ab6914694ed2be974a9ed5528ddac759e51', '1da7e0b46a3932ccee5832bd6e3761c90527bb5b8ce05023f63fb990be881247', '40b94ecb2718f3c5c6d32e12c0cac5c6af9b67dffc6369c317fb0d7bb3f07ac4'], '.claude/commands/briefing.md': ['26a71b8e290d9fdee562063a6f15897e6b192c9cc9c78ec8669772b777ad4c8e'], '.claude/commands/employee.md': ['d0a76670ccff7404c00e1887776de01492ade96adf4d30a3b381e7fc2fde9b7c'], '.claude/commands/onboard.md': ['971879f3feb22125639e3e4cf11d23778259664b7bc9dd087af30213bfcc5fb9', '66c797ff253d92c92bb41a0d5f4d94c980b774a4406972992f9565cd68577fee'], '.claude/commands/tidy.md': ['bc7ef4b37db185c9384e7ec0d57ab3f51601da4b264a5be8bfe8d55b5bbe5d04', '1c1086a4e718e4fbe7ce8bfb7ef63d4d5a87893a3ed1e4c34b8ad35b55fa7a53'], '.claude/commands/weekly.md': ['2b67418377050ba4bcd0c9afb4b6b550a5ef51228611497e2965c31b7a72cafa'], '.claude/settings.json': ['28e84d6b8e9b7aab40bf4dafeca0eae9579b6a365aa1170c762d0c1d2701cedf', '013326d496b6f4946ac37da70080c6f0f97b30685890b141cb09468b67d79422', '7e652767c26949981661e222dad9f071b9747dc137138c0025e44402e0c743b3'], '.claude/skills/course-kit-20261109/8블록_요청문.md': ['0607a7d072f29af56c6b017ad8aed6016b5b087fbde5e748cb48b93bcc0c284d', 'ad8bc89f9980ef16a0abfbd33a5bfdbd1b87dd575edf35e584cd6f84cbb4b691'], '.claude/skills/course-kit-20261109/내 업무 소개.md': ['c65aa85fefec87b92449e466fa39fcf7ab9a31cd6d2607c9eb8ce64009e0eb71', '0e5082168ff44d9273570ab3ea9b3d1bac5ef9eee203cc7753991516fceceea0'], '.claude/skills/course-kit-20261109/내_결과_찾기.md': ['81229ef5a7432f144c16e3d78386281ef7a6ffb878108c37a5302e7150664568', 'c15310f07b5e3302636f43f16163e5fa5e2702ae95eb350f31e3ae684c555e2a'], '.claude/skills/course-kit-20261109/사례_5개_빈양식.md': ['6c357da0e368bd108f1c4e1f990d10ab4dd2f5a573ae02f954a0ed12e639a79a', 'decbbe33b75fedfa30a1538593c2d3f46145f6cd3f5441c881d3bce20d0f695e', '4f7798c989ec2fa3e17b4348811808ad31171f182308c6671ea2031f61b661f2'], '.claude/skills/course-kit-20261109/시작과_막힘_복구.md': ['fed001f6ba691867b8489f87fbc06c8f3971c0fa65c732e1fb48b057796f6c84', '5e319ba93280fe5cc0e0628411ad7091e4f004bd6ee8500ab8cee88c3353d288'], '.claude/skills/course-kit-20261109/월요일_요청문_6개.md': ['516dd67cfef81b41790e7d2b6963de5601f25bf709279a49be1014ee764ecb04', '8fa1ecefeafe3c2bc1c5f9bc4f6d8cbc66a97594f4d19f65a9f06825b196b983'], '.claude/skills/course-kit-20261109/이어가기_메모.md': ['214c38dfe73086a1083f672ed6666069039e0ba25448e5f630db0825ca72cbfc', '699860f71f522dfdf7ccc796b4e9f9090296c49451acb3399decb42b8d171fc7'], '.claude/skills/course-kit-20261109/자주 받는 질문.md': ['85aeeacc26e77ed972634a9984960f56521fa5e0a571bb6ef132b3a8da48e91c', '2934d135d4bd98cb74662fdc7bb2eb80c3de9f05779321ea11f03d7587edfe5a'], '.claude/skills/course-kit-20261109/작업 기준.md': ['84af5bc42b3f1cdee370b9395acee937a96a7e5c096daff46f8fd2067f37bbd3', 'c0ad057727967c11069e8124829860de820e4c70fc0bbecc6924abedb4d5bbe1'], '.claude/skills/course-kit-20261109/작업_연습.md': ['02b484edc4eb46327748e8968dcc69b0c6628022c4286ea24555e6782ec9e50e', '0d2fa93d3bebecfab4b3240877d630d14b2067f3861a9fafc6216fa41c13b858'], '.claude/skills/course-kit-20261109/전후_비교.md': ['b22f01fdf7f328ab15fd8b4ec2f25dd3c31a6a2a2d5f260524a168e2a2af5c5d', '3b97ed19cddfbdff84ca6bdd095fd803c898f3ceaae85aec2c1878c4146d180f'], '.claude/skills/ilson-motion/SKILL.md': ['6148a6870a954f765657f62d9cf24739850f1dbac9154491df561a2a968d4d7c'], '.claude/skills/ilson-search/SKILL.md': ['55817a5ff3d04aab280881d9e88f843f228f380e0f0f46d591b73aca8c169e8a']}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def run(template, home):
    template, home = Path(template), Path(home)
    manifest = home / '.updates/installed.json'
    try:
        installed = json.loads(manifest.read_text()).get('files', {}) if manifest.is_file() and not manifest.is_symlink() else {}
    except (OSError, ValueError):
        installed = {}
    sources = [template / 'CLAUDE.md'] + sorted((template / 'claude').rglob('*'))
    conflicts = []
    for source in sources:
        if not source.is_file():
            continue
        rel = Path('CLAUDE.md') if source == template / 'CLAUDE.md' else Path('.claude') / source.relative_to(template / 'claude')
        target = home / rel
        for parent in [target, *target.parents]:
            if parent == home:
                break
            if parent.is_symlink():
                raise ValueError('설치 대상에 연결 경로가 있습니다')
        if target.exists():
            if not target.is_file():
                raise ValueError('설치 대상이 일반 파일이 아닙니다')
            existing = digest(target)
            allowed = set(BASELINE.get(rel.as_posix(), [])) | {installed.get('box/' + rel.as_posix()), digest(source)}
            if existing not in allowed:
                conflicts.append(rel.as_posix())
                continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for item in conflicts:
        print('사용자 수정 보존(자동 갱신 안 됨):', item)
    if 'CLAUDE.md' in conflicts:
        print('학습 지침 준비 미완료: 기존 CLAUDE.md를 검토한 뒤 새 Box 지침을 반영하세요.')

if __name__ == '__main__':
    try:
        run(sys.argv[1], sys.argv[2])
    except (OSError, ValueError):
        print('Box 지침 설치 실패: 파일과 폴더를 확인하세요.', file=sys.stderr)
        sys.exit(1)
