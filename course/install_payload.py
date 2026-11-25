"""Install the embedded course helper without replacing existing files."""
import base64
from contextlib import contextmanager
import errno
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

IS_WINDOWS = os.name == 'nt'
ELEVATED_FALLBACK = '관리자 권한 PowerShell에서 만든 파일이 있습니다. 「관리자: Windows PowerShell」에서 ilson doctor --fix-permissions 를 실행해주세요.'
REDIRECTED_FALLBACK = '관리자 권한 창에서는 연결(바로가기)을 거치는 경로의 파일을 바꾸지 않았습니다. 일반 PowerShell 창에서 ilson doctor 로 확인해주세요.'
UNSCANNED_FALLBACK = '관리자 권한 창에서 일부 폴더는 안전 확인을 끝내지 못해 권한을 바꾸지 않았습니다. 「관리자: Windows PowerShell」에서 ilson doctor --fix-permissions 를 다시 실행하고, 그래도 남으면 강사에게 확인해주세요.'
# README's student install command. When an install fails, the helper left in place may predate
# `ilson doctor --fix-permissions` (e67f806 has no such flag); an elevated rerun of the installer
# always works, because its final repair pass hands the tree back to the user.
WINDOWS_INSTALL_COMMAND = 'irm https://raw.githubusercontent.com/jakeparkcolde/ilson-box/main/course/install-windows.ps1 | iex'
RERUN_ELEVATED_HINT = ('관리자 권한 PowerShell에서 만든 파일 때문에 설치를 마치지 못했습니다. 시작 메뉴에서 Windows PowerShell을 '
                       '마우스 오른쪽 버튼으로 눌러 「관리자로 실행」을 고른 뒤, 「관리자: Windows PowerShell」 창에서 설치 명령을 다시 실행해주세요: '
                       + WINDOWS_INSTALL_COMMAND + ' 설치가 끝나면 평소처럼 일반 PowerShell 창에서 계속하면 됩니다.')

# Fixed reasons the helper install stops before it changes any helper file (earlier installer
# steps may already have run). The helper prints only the code (HELPER_REFUSED=<code>) and exits
# with its number; the installers show the Korean line for the number
# (install_diagnostics.HELPER_REFUSALS), because they drop the helper's stderr. 3 is the
# permission-denied exit above.
REFUSAL_EXIT = {'ADMIN_RUNNING': 4, 'INSTALL_BUSY': 5, 'HELPER_MODIFIED': 6}

# What a non-blocking lock reports when another process holds it: flock EWOULDBLOCK/EAGAIN,
# msvcrt.locking EACCES (or EDEADLOCK). Any other OSError is a real I/O failure and keeps its own
# reason (review D23 note 4). Decided per call, like the lock branch itself.
def lock_held(exc):
    held = ({errno.EACCES, getattr(errno, 'EDEADLOCK', errno.EDEADLK)} if os.name == 'nt'
            else {errno.EWOULDBLOCK, errno.EAGAIN})
    return isinstance(exc, BlockingIOError) or getattr(exc, 'errno', None) in held


class Refusal(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# Only exact published/baseline bytes may be replaced. Unknown user edits stay intact.
KNOWN_HELPER_SHA256 = {'ilson.py': {'70c922f15483534e401dccf7f7fefdea88c4be1102b32196ad00fb60f4fa4bff', 'b8491dea3dd3f9b9bf82070c0a054d669386f083a68f1380f0a44e6a141cc5e4', 'b1f72a5e2c9fcb715ce8d58560a22a076f0f126333c154ad7b28100adcdd53d2', '39d10d5e65089bc23e53c09e720e594195891ccb60438253651de6546bb83182'}, 'license.py': {'4b6e50b84073c6e8178b3c0c3c8055839a9d7d607be284ce3e0651e929e15ba9'}, 'selflearn.py': {'48b6804a599765af19f6ab35c75409986fb5bd3e52967bdd52d1386119ee528d', 'b1eabe4380dbd53cc3f35d1a0a82f511f96b04320b2bb585925478f7d8e60b68'}, 'skill_share.py': {'b233d29be73af4e7f9c63a3e948b51ee2946607ea61b71c30f9c473e82fa7412'}, 'weekly_summary.py': {'10a7935d68726ef63457014e64a2702ba0a22167a65c8aa002f3e8a994d48bf7'}, 'install_diagnostics.py': {'0666c62d3668573dbea1ae370aed1e7b9f5b2abd7737c87a8b93e95bd2803ea7', 'ec125e4c085251f010fc414fc91609933ae4da87a4c9dbb06c81d16778d20343'}}
KNOWN_HELPER_SHA256['ilson.py'].add('752358c3547b3d3e46924b95916de06b239d8153df4bf262ff096d3255392aa3')
KNOWN_HELPER_SHA256.update({
    'usage_timeline.py': {'5f8b67118d836da300a945368ada6eb7156b2f0f03b56d7cdebdd7733eb4e43e'},
    'usage_sync.py': {'5343e58ce4cad29b316b359ce54030403764c2413eddcab28ac1cf4275b322b6'},
})
# Exact d25b333 bytes: permit the curator fix and bootstrap upgrade/rollback.
KNOWN_HELPER_SHA256.update({
    'curator.py': {'9d31913c714350581527d1d14e5083b65ab830cb3f687dfc486a701933a40b92', '95fa87b804d129d4bb307f1d4dad97d52feb23f92c01da883aab5f111acb8567'},
    'install_payload.py': {'99ab46f43a2dbaae7299e356d8ecb93a2cbe178ae46e2cb8927bc9506ebe0469', 'b8d551e301e2f713854ef8643638764da7c464ceff369d22792b180bdbeec847'},
})
# Reviewed parent/published course bytes, plus the first admin baseline.
for _name, _hashes in {'ilson.py': {'b659e309797637e4a7f6c9548985d82f72ed0afa6ab8ca6467d1ea2519612feb', '752358c3547b3d3e46924b95916de06b239d8153df4bf262ff096d3255392aa3'}, 'install_payload.py': {'5435341cddb4497461306c097283fbb0f2e356ed98998e482c9710d89db841cb', '36c53aec20c4648959093926368dc5ca56dcec8b8831838b9b127ae232ce42f5'}, 'curator.py': {'486fc5e208dec33559ca5540cd0ec07883affde170b8fef54b50d8e6c251d454', '9d31913c714350581527d1d14e5083b65ab830cb3f687dfc486a701933a40b92'}, 'course_update.py': {'9d3c1fbd03cb085f80afbf17310306c1a9fecea866f45b99015911a876aace60'}, 'usage_timeline.py': {'dc78d0f469cfbb79135090589d8f8c291de14a6634a82186824e6f744014c917'}, 'usage_sync.py': {'c9836b0fd69ce30526d281378035b9c8c9b1648cb07a228ff55b17cc606cbcbf'}, 'license.py': {'4b6e50b84073c6e8178b3c0c3c8055839a9d7d607be284ce3e0651e929e15ba9'}, 'selflearn.py': {'b1eabe4380dbd53cc3f35d1a0a82f511f96b04320b2bb585925478f7d8e60b68'}, 'weekly_summary.py': {'10a7935d68726ef63457014e64a2702ba0a22167a65c8aa002f3e8a994d48bf7'}, 'skill_share.py': {'b233d29be73af4e7f9c63a3e948b51ee2946607ea61b71c30f9c473e82fa7412'}, 'install_diagnostics.py': {'96caadd67e95272b6a46688f6f38aa1eb684b6ed6b826cdbc1318fe45ecdf806'}, 'web-admin-server.py': {'4d3c041fa13dd2010fc0cf63402e57ce8bc6ede3afcd39ef260f52ba28772039'}, 'web-admin.py': {'cb804fcae7e16a889286a3e5175d8bfc60100c4b8abc9195dcd33e0eeef13b77'}, 'course_admin.py': {'eeaf8b25f0e68cfc37d0d877f52f1b977fa385d32395d4a594e30ae3eedb66e7'}, 'ilson_platform.py': {'4f944d6eecc3dba4576de30bec3b67656a3bb8d551ac9f5051fb79a9a6cddf2a'}, 'access_policy.py': {'fa675442435bd1098ae6dbc2c0ed26076b24c0c1a1ec288172a2012ecd0957d7'}, 'approval_store.py': {'1d669cf478414c184a6c180aa6251da6e02cab0474efe210ee4240e1a7400698'}, 'approval_dispatch.py': {'7acc7fbf932ed686599c8f6195425e511d07438dc4ed14c7f783b37fe7b6431a'}, 'approval_actions.py': {'1fa80c0867beccae68fc31c29d7e1dc9fe5c5661a2074e082b12ce056eebde83'}, 'runtime_gate.py': {'02b3dcee689c8442eeed56370899c2d252f1c3c5f44a18cbe07edbd50e23348d'}, 'replies_draft.py': {'4a35668cbcecb4145d6900bec737fe4c7dd1ed3acfbb84cd77b8bf2df9592025'}, 'web/course.html': {'3422ad9638fe10e7b3346e26a48ecba6f953e6c0ba197c359795c0631ffb839f'}, 'web/course.js': {'19291cf19369aad4f903a5eb83be47bb890c81a6e96288dbbfa8072c20cae23a'}, 'web/course.css': {'fe27bc91bfdabb5c2f4b7a00af3bb1d216c9fa525c25a45f0d9590a5a1e3f94d'}, 'web/current/base.css': {'f91b260c336d23c788435b94ac3fb03a665c3a0e7adb235ff8a4259fe689955d'}, 'web/current/shell.css': {'fdb8d1ec1fd034bee739a7e95e681b95b65d62fb28e5a550fe48e43090472b9d'}, 'web/usage-history.js': {'86dc602a1a03691090abbe12ec92ad1129e8c392a06e1540eb85ff887d47fc5d'}, 'web/usage-history.css': {'da8c6732c858435bfec5bf28c29709b99710ac823c1eb97002c905d396106ea2'}}.items():
    KNOWN_HELPER_SHA256.setdefault(_name, set()).update(_hashes)
# Exact pre-Herdr admin baseline 26f69df; permit a reviewed staged upgrade.
KNOWN_HELPER_SHA256.setdefault('install_diagnostics.py', set()).add('96caadd67e95272b6a46688f6f38aa1eb684b6ed6b826cdbc1318fe45ecdf806')
KNOWN_HELPER_SHA256.setdefault('ilson.py', set()).add('d48cf75eeebab0d29f7094be45729fcd47a1491c85382833f2e86c0b676e35ec')
KNOWN_HELPER_SHA256.setdefault('install_payload.py', set()).add('237aa891c9a37e078a540c44312e8b1ad8e4cd0c31313d2ddfb56a454efba678')

# Exact embedded bytes of the reviewed admin stage before the Herdr step.
for _name, _hashes in {'access_policy.py': {'fa675442435bd1098ae6dbc2c0ed26076b24c0c1a1ec288172a2012ecd0957d7'}, 'approval_actions.py': {'1fa80c0867beccae68fc31c29d7e1dc9fe5c5661a2074e082b12ce056eebde83'}, 'approval_dispatch.py': {'eee61a806a90ccfcf195364c20cf643c82add672a801e20d969ad1751ec497d2'}, 'approval_store.py': {'5491fa48da41b40a4abc9eb14ce874a149b3d817857e6a11eff35f529ad92048'}, 'course_admin.py': {'eeaf8b25f0e68cfc37d0d877f52f1b977fa385d32395d4a594e30ae3eedb66e7'}, 'course_update.py': {'9d3c1fbd03cb085f80afbf17310306c1a9fecea866f45b99015911a876aace60'}, 'curator.py': {'486fc5e208dec33559ca5540cd0ec07883affde170b8fef54b50d8e6c251d454'}, 'ilson.py': {'d48cf75eeebab0d29f7094be45729fcd47a1491c85382833f2e86c0b676e35ec'}, 'ilson_platform.py': {'6d3835f42250e297ecfeda3352ad25ee3f6b1d415577d9b69189611ede7d09cc'}, 'install_diagnostics.py': {'96caadd67e95272b6a46688f6f38aa1eb684b6ed6b826cdbc1318fe45ecdf806'}, 'install_payload.py': {'237aa891c9a37e078a540c44312e8b1ad8e4cd0c31313d2ddfb56a454efba678'}, 'license.py': {'4b6e50b84073c6e8178b3c0c3c8055839a9d7d607be284ce3e0651e929e15ba9'}, 'replies_draft.py': {'8d59488998de4364acfd21d3505c4e60be7a785403c9c9ff1c9d76e881f6ed0f'}, 'runtime_gate.py': {'02b3dcee689c8442eeed56370899c2d252f1c3c5f44a18cbe07edbd50e23348d'}, 'selflearn.py': {'b1eabe4380dbd53cc3f35d1a0a82f511f96b04320b2bb585925478f7d8e60b68'}, 'skill_share.py': {'b233d29be73af4e7f9c63a3e948b51ee2946607ea61b71c30f9c473e82fa7412'}, 'usage_sync.py': {'c9836b0fd69ce30526d281378035b9c8c9b1648cb07a228ff55b17cc606cbcbf'}, 'usage_timeline.py': {'dc78d0f469cfbb79135090589d8f8c291de14a6634a82186824e6f744014c917'}, 'web-admin-server.py': {'1c193e88743bc14ad9ee4cf4d28d233538139aae0028917d479d32e3896f6483', '83832091b21535b90a858e5717a48a47d6f3b1296f1ed0d4c4501def69e29164'}, 'web-admin.py': {'cb804fcae7e16a889286a3e5175d8bfc60100c4b8abc9195dcd33e0eeef13b77'}, 'web/course.css': {'fe27bc91bfdabb5c2f4b7a00af3bb1d216c9fa525c25a45f0d9590a5a1e3f94d'}, 'web/course.html': {'3422ad9638fe10e7b3346e26a48ecba6f953e6c0ba197c359795c0631ffb839f'}, 'web/course.js': {'d68aa4c66e17847b4a516c0afd3b4ad42312492a1ab08042ca9f6bac9f215931'}, 'web/current/base.css': {'f91b260c336d23c788435b94ac3fb03a665c3a0e7adb235ff8a4259fe689955d'}, 'web/current/shell.css': {'fdb8d1ec1fd034bee739a7e95e681b95b65d62fb28e5a550fe48e43090472b9d'}, 'web/usage-history.css': {'da8c6732c858435bfec5bf28c29709b99710ac823c1eb97002c905d396106ea2'}, 'web/usage-history.js': {'3ee1907859b237358346a7a3ee95f0a39d6e7d9145daf57e61f29eea971372e2'}, 'weekly_summary.py': {'10a7935d68726ef63457014e64a2702ba0a22167a65c8aa002f3e8a994d48bf7'}}.items():
    KNOWN_HELPER_SHA256.setdefault(_name, set()).update(_hashes)

KNOWN_HELPER_SHA256.setdefault('install_payload.py', set()).add('ecbb6520eac95e7a144425169fb0c920e377caf084e46af77db47010574b5645')
# Exact origin/main (bbd7c40) bytes before V2 short serial support.
KNOWN_HELPER_SHA256.setdefault('license.py', set()).add('4fce712766ab7627a6965e2045f5a747dfe15e15695b81ee474c5679f0fe7fae')
KNOWN_HELPER_SHA256.setdefault('install_payload.py', set()).add('eff01b3378c887890a9b2709193d3fc973023d06f2054dea2f057b6bf4dfd53b')
# Exact origin/main (d8c9c7c) bytes before peer switcher support.
for _name, _h in (
    ('web-admin-server.py', 'ee3dc33c46a8ba530aaed128ca186648c52a2a895a313e9a05749c9964d8dbda'),
    ('web/current/shell.css', 'c09a66d587dd7527678b9ff9212af10f95a90bee22d52ca6f5c2eeed6a89f75f'),
    ('web/current/base.css', '8bf7713ace7314719a3ef9a54b6fa1db7343b6b24063c1f4664838955eb21dca'),
    ('install_payload.py', 'b8156310eddff24df137ef22edef36f2c0e19143d1fe44cf8b3b8d90af9740eb'),
    ('license.py', 'be7ee35bc83bcd40786be9f9760e67c0579805737f4321c4289943c40b5ee7f7'),
):
    KNOWN_HELPER_SHA256.setdefault(_name, set()).add(_h)
# All historical shipped installer payload/bootstrap bytes (including d78cd11) so any
# previous official course installation upgrades automatically without HELPER_MODIFIED.
for _name, _hashes in {
    'course_admin.py': {
        '3d32ca8f0db4ac184f4456ed11090bf0a99ab24ba34a1af0310af4115109c600',
        '45a673defef80fe4363e71337267bfe0eabade2ef735f8dd7d40d1efcb852e00',
        'b46c6430f9e494cf0d1b9230ba6d799f8412d267c543ea2f13a18f8bed92fcc0',
    },
    'course_update.py': {
        '53a68fdbfcc0926f19feddaf9724d89de3b97760149124959f67d20490aff862',
    },
    'ilson.py': {
        '4617b85cd4e0ee0348732d7c24672f7c05026222e691599e4327e91004586d5a',
        '5f7ea11afe8f9ada1808ce39e7aa3ac51dc902bcc8378e1ce35cc75c7e4087bc',
        '9d2f9d66b46949c3b9a228011861958093fd008cd4176ffe2f6b3d4b00b6a237',
    },
    'ilson_platform.py': {
        '804b8af7fd370d4763ed8045ee9e2b446e49755a3dc23b28e4b11527e03e49b6',
        '8fd883c4df503e710e8d9877026fbe5b11813a8a15ff8831fe415526497706c7',
    },
    'install_diagnostics.py': {
        '1031e0229313ad66a7a6e08e0927fa3cd0879ab7ce750d15515281c2f64eb2a2',
        '3c0d93eb8832fd197f1e7049610cf330582ceab958f5511d5ddca2233b46dc14',
        '91be3415d47322743f531646300221f25d630badbec376a8242e5734b93df2fe',
        '97d859e832901300ae435081f9c243584be4258a3cd0c319c8829b84c317c545',
        'ba9e15e8e1df12c07512e51cf8b80cce7593df43c97c20316b9e76c5dc3ac5c0',
        'bae7d7d4cb6cc75eb8de804989a2f7553bfdae8834ef3f5033653a1ab7f98b76',
        'bf7cc2c70b42e3186c410bc8495b77f49c0a881c4569e20ecba2a70bf70a7a4c',
        'e31f8377833d7c2f7cb7c56ec6ac37a06a27e90238b244a78c8a49853fa57974',
    },
    'install_payload.py': {
        '0e93c48a7c666c61bb9db0b546b3021bee089e4124a11377f6c601a88dc9e49a',
        '1645ef8579bd0bafbb03bb7de03e91c876e971d836445e6a7af612da769ed677',
        '22ad058a566c56f8edc8558753d64e77966e2d30174157cc929e3bba0455a9dc',
        '24f76d2b5682845e7491378e950f043a83a3ac6e894219c58b881e136b476fc5',
        '425d2e4c75082cb64f4526565f190cf1253ced49037636d35c50e6b333529315',
        '4bcad192c46a5c33e6c818a856300c0ba3cfc8db619016c88bfe4a9d7d2b0384',
        '4ecc5a48eaeb709606dadfbcb5999e72c2a4459b381b8a9bf22e9e77138c890d',
        '56f3223721dc735bb717845bae671d186eff840374a9eaef36616fc3341072a2',
        '5d862694b7778ee1ed3444491fe04a5dacd456adfd016d1c3b54f142bafe40a7',
        '7fbb75f6b99aa3f0469897fd4f97cd29cbe04a03533aa63ed20bbc14a17d02f6',
        '82cadd1c84604e52b362e5aac48bbbdc734de3c35d782b127a4b69e45203fec6',
        '83446da44b6661b8b659b6629064f63f5758ae0d38c81e1474fbf606d1f4f066',
        '8bfe9823d386c055eed52d798563f1e63fabf0df0d45798b980ea5c7b168d1ac',
        'ca1f9650252e01a9da884cbf8406a7928f165b2f0414ca513aa7759b70588e90',
        'd0f0d0f9425c5dd6c987343ab6a1157ce15bbf6cc4843f11160fbdff07dee191',
        'f2ae01d39b1c3fad40fc2506cb7b5ad080688967eec1e0fcb46ee4fbb7be3fa3',
    },
    'license.py': {
        '1b67385d7271657629725ee4646d9c7257e5894ebad9c3b5eba0354c195e94b5',
        '8ef253fa7eed1ff40c756f439c56b62a3628e4e977b777db95a251a0fe147706',
        'dd1a26eec3f51353dc840f5d62ccb1dc34abf06a3d7b85dad311a2b06d0e19a9',
        'fcbdc20fc77b3ff43936867949a9411fc45b47747853633d22284cdd205e413a',
    },
    'usage_sync.py': {
        '921e548f6869048c2bbc371dfa420c2c829706bf441e435832179ce58beb515b',
    },
    'usage_timeline.py': {
        'ba1f2f4c317b2779866cf55d4dcaa05c455b60b2dcfd2e8a831f260ce0a1d860',
    },
    'web-admin-server.py': {
        '1c1d3396edce5c7d3e1ac80abac70ef8e351afb6ad1d16a04b0fc7340b23ede4',
        '6d01a90c927767a6bf9721d0fea674c0a3ed5f80dd064ef6524300179a00cb32',
        'e6211b236390e3db2edc21604fc36251368267f88a887cd3423453d45a0eaa33',
    },
    'web/current/shell.css': {
        'beb92e833c78865e659808ea646ff3ffc14df9b401a395b80bde281c57ce6b3a',
    },
}.items():
    KNOWN_HELPER_SHA256.setdefault(_name, set()).update(_hashes)

ADMIN_FILES = {'web-admin-server.py', 'web-admin.py', 'runtime_gate.py', 'ilson_platform.py', 'replies_draft.py', 'access_policy.py', 'course_admin.py', 'approval_actions.py', 'approval_store.py', 'approval_dispatch.py'}
WEB_FILES = {'web/course.js', 'web/usage-history.css', 'web/current/base.css', 'web/current/shell.css', 'web/usage-history.js', 'web/course.html', 'web/course.css'}
ALLOWED_FILES = set(KNOWN_HELPER_SHA256) | ADMIN_FILES | WEB_FILES | {'course_update.py'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe(path):
    for part in [path, *path.parents]:
        if (sys.platform == 'darwin' and str(part) in ('/var', '/tmp', '/etc')
                and part.is_symlink() and os.readlink(part) in ('/private' + str(part), 'private' + str(part))): continue
        try: info = part.lstat()
        except FileNotFoundError: continue
        if part.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('helper path is a link')
        if part.is_file() and info.st_nlink != 1:
            raise ValueError('helper path is shared')


def atomic_write(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.ilson-update-', dir=path.parent)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)


@contextmanager
def update_lock(root):
    safe(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / '.install.lock'; safe(path)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        info = os.fstat(fd)
        if info.st_nlink != 1: raise ValueError('invalid install lock')
        if os.name == 'nt':
            import msvcrt
            if not info.st_size: os.write(fd, b'0')
            os.lseek(fd, 0, 0)
        else:
            import fcntl
        try:
            if os.name == 'nt': msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if not lock_held(exc): raise
            raise Refusal('INSTALL_BUSY', 'another install is running') from None
        with admin_stopped(root):
            yield
    finally:
        os.close(fd)


@contextmanager
def admin_stopped(root=None):
    """Use code identity as well as state, including a custom course state home."""
    state = Path(os.environ.get('ILSON_COURSE_STATE', Path.home() / '.ilson-course'))
    paths = ([Path(root) / '.admin.lock'] if root is not None else []) + [state / 'state/web-admin/server.lock']
    held = []
    try:
        for path in paths:
            safe(path)
            if not path.exists(): continue
            fd = os.open(path, os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0))
            held.append(fd)
            if os.fstat(fd).st_nlink != 1: raise ValueError('invalid admin lock')
            try:
                if os.name == 'nt':
                    import msvcrt
                    if not os.fstat(fd).st_size: os.write(fd, b'0')
                    os.lseek(fd, 0, 0)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if not lock_held(exc): raise
                raise Refusal('ADMIN_RUNNING', '관리 화면을 먼저 끄세요: ilson admin stop') from None
        yield
    finally:
        for fd in reversed(held): os.close(fd)


def acl_module(files):
    """The ACL helper of the bundle being installed; a fresh install has no license.py yet."""
    import types
    module = types.ModuleType('ilson_install_acl')
    exec(compile(files['license.py'], 'license.py', 'exec'), module.__dict__)
    return module


def elevated_hint(files):
    try: return acl_module(files).ELEVATED_OWNER_HINT
    except Exception: return ELEVATED_FALLBACK


def redirected_hint(files):
    try: return acl_module(files).REDIRECTED_HINT
    except Exception: return REDIRECTED_FALLBACK


def unscanned_hint(files):
    try: return acl_module(files).UNSCANNED_HINT
    except Exception: return UNSCANNED_FALLBACK


def repair_owner(root, files, installed=True):
    """Windows: an elevated installer leaves every object owned by BUILTIN\\Administrators and
    mkdir(0o700)/mkdtemp folders without the user. One pass gives them back to this user.
    installed: the new helper (with ilson doctor --fix-permissions) is in place."""
    if not IS_WINDOWS: return None
    tree = root.parent if root.name.lower() == 'lib' else root
    try: counts = acl_module(files).windows_tree([tree], repair=True)
    except Exception:
        print('HELPER_PERMISSIONS=unverified')
        return None
    left = counts['no_access'] or counts['foreign']
    refused = counts.get('refused', 0)  # the guarded repair left a linked path alone: not a reason to rerun elevated
    unscanned = counts.get('unscanned', 0)  # a folder's safety scan did not finish: not a link either
    print('HELPER_PERMISSIONS=' + ('ok' if not left and not refused and not unscanned else 'left'))
    if left: print(elevated_hint(files) if installed else RERUN_ELEVATED_HINT)
    else:
        if unscanned: print(unscanned_hint(files))
        if refused: print(redirected_hint(files))
    return counts


def target(root, name):
    if name not in ALLOWED_FILES: raise ValueError('invalid helper file')
    return root.parent / name if name in WEB_FILES else root / name


def _is_known_existing(name, old):
    known = KNOWN_HELPER_SHA256.get(name, set())
    if digest(old) in known:
        return True
    if b'\r\n' in old and digest(old.replace(b'\r\n', b'\n')) in known:
        return True
    # Allow seamless upgrade of any early pre-V2 official license.py (which still gets backed up).
    if (name == 'license.py' and len(old) <= 65536
            and b'"""Ilson serial verification and offline lease state, stdlib only.' in old
            and b"PUBLIC_KEYS = {1: bytes.fromhex('6455f743370eba4adf230aeb65b23fc2cd4e0ff7df35108e48e2c63bf0f35feb')}" in old
            and b"DOMAIN = b'ILSON-LICENSE-V1\\0'" in old
            and b'is_short_serial' not in old):
        return True
    return False


def install(root, files, verify=None):
    safe(root)
    if root.exists() and not root.is_dir(): raise ValueError('helper directory is not a normal directory')
    if set(files) != ALLOWED_FILES or any(not isinstance(value, str) for value in files.values()):
        raise ValueError('invalid helper bundle')
    changes = []
    for name, content in files.items():
        data = content.encode('utf-8')
        if name.endswith('.py'): compile(content, name, 'exec')
        path = target(root, name); safe(path)
        if path.exists() and not path.is_file(): raise Refusal('HELPER_MODIFIED', 'existing helper differs; ask the instructor')
        old = path.read_bytes() if path.exists() else None
        if old == data: continue
        if old is not None and not _is_known_existing(name, old):
            raise Refusal('HELPER_MODIFIED', 'existing helper differs; ask the instructor: ' + name)
        changes.append((name, path, old, data))
    with update_lock(root):
        installed = False
        try:
            result = _apply(root, changes, verify)
            installed = True
            return result
        finally:
            repair_owner(root, files, installed)


def _apply(root, changes, verify):
    if not changes:
        if verify: verify()
        print('HELPER_STATUS=UP_TO_DATE')
        return None
    upgrading = any(old is not None for _, _, old, _ in changes)
    base = root / '.install-backups'; safe(base); base.mkdir(mode=0o700, exist_ok=True)
    seq = next_backup_seq(base)
    backup = Path(tempfile.mkdtemp(prefix='upgrade-', dir=base))
    manifest = {'schema': 1, 'seq': seq, 'status': 'pending', 'files': []}
    for name, path, old, data in changes:
        if old is not None:
            saved = backup / name; safe(saved); saved.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            saved.write_bytes(old)
        manifest['files'].append({'name': name, 'before': digest(old) if old is not None else None, 'after': digest(data)})
    (backup / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True), encoding='utf-8')
    applied = []
    try:
        # Dependencies/assets first, entry point last. Validate targets again under lock.
        for name, path, old, data in sorted(changes, key=lambda item: item[0] == 'ilson.py'):
            safe(path)
            current = path.read_bytes() if path.exists() else None
            if current != old: raise Refusal('HELPER_MODIFIED', 'existing helper changed; ask the instructor')
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if old is None:
                with path.open('xb') as stream: stream.write(data)
            else: atomic_write(path, data)
            applied.append((name, path, old, data))
        for name, path, _, data in changes:
            if path.read_bytes() != data: raise ValueError('helper verification failed')
        if verify: verify()
    except Exception:
        for name, path, old, data in reversed(applied):
            safe(path)
            if path.read_bytes() != data: continue
            if old is None: path.unlink()
            else: atomic_write(path, old)
        manifest['status'] = 'failed'
        atomic_write(backup / 'manifest.json', json.dumps(manifest, sort_keys=True).encode())
        raise
    manifest['status'] = 'applied'
    atomic_write(backup / 'manifest.json', json.dumps(manifest, sort_keys=True).encode())
    print('HELPER_STATUS=' + ('UPDATED' if upgrading else 'INSTALLED'))
    print('HELPER_UPGRADE_BACKUP=' + backup.name)
    return backup


def backup_seq(manifest):
    """The creation order an install recorded in its backup manifest; None for backups of helpers
    that recorded none (public e67f806 and older)."""
    value = manifest.get('seq') if isinstance(manifest, dict) else None
    return value if type(value) is int and value > 0 else None


def next_backup_seq(base):
    """1 + the highest order any backup records, whatever its status. Read under the install lock,
    so two installs never share a number. Folder times play no part: copying or re-creating a
    backup folder changes them (laptop run 3, N7)."""
    top = 0
    for backup in base.glob('upgrade-*'):
        path = backup / 'manifest.json'
        try:
            safe(path)
            top = max(top, backup_seq(json.loads(path.read_text(encoding='utf-8'))) or 0)
        except (OSError, ValueError):
            continue
    return top + 1


def _rollback(root, backup):
    safe(root); safe(backup)
    if backup.parent != root / '.install-backups' or not backup.name.startswith('upgrade-'):
        raise ValueError('invalid helper backup')
    manifest_path = backup / 'manifest.json'; safe(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    changes = []
    if manifest.get('schema') != 1: raise ValueError('invalid helper backup')
    seen = set()
    for item in manifest['files']:
        name = item['name']
        if name not in ALLOWED_FILES or name in seen: raise ValueError('invalid helper backup')
        seen.add(name)
        path = target(root, name); safe(path)
        if not path.is_file() or digest(path.read_bytes()) != item['after']:
            raise ValueError('existing helper changed; rollback preserved user edits')
        data = None
        if item['before'] is not None:
            old = backup / name; safe(old); data = old.read_bytes()
            if digest(data) != item['before']: raise ValueError('invalid helper backup')
        changes.append((name, path, data, path.read_bytes()))
    applied = []
    try:
        for name, path, data, installed in sorted(changes, key=lambda item: item[0] == 'ilson.py'):
            safe(path)
            if path.read_bytes() != installed: raise ValueError('existing helper changed during rollback')
            if data is None: path.unlink()
            else: atomic_write(path, data)
            applied.append((path, data, installed))
    except Exception:
        for path, data, installed in reversed(applied):
            safe(path)
            current = path.read_bytes() if path.exists() else None
            if current == data: atomic_write(path, installed)
        raise
    manifest['status'] = 'rolled_back'
    atomic_write(manifest_path, json.dumps(manifest, sort_keys=True).encode())


def rollback(root, backup):
    with update_lock(root):
        _rollback(root, backup)


def main():
    try: _main()
    except Refusal as refusal:
        print('HELPER_REFUSED=' + refusal.code)
        sys.exit(REFUSAL_EXIT[refusal.code])


def _main():
    root = Path(sys.argv[1]).absolute()
    if len(sys.argv) == 4 and sys.argv[2] == '--rollback':
        rollback(root, root / '.install-backups' / sys.argv[3]); return
    # The installer streams the bundle after its bootstrap line. Neither environment
    # variables nor command-line arguments can carry arbitrarily large bundles.
    files = json.loads(gzip.decompress(base64.b64decode(sys.stdin.buffer.read())))
    try: install(root, files)
    except PermissionError:
        if not IS_WINDOWS: raise
        # The installer suppresses stderr; this fixed line is what the student sees. The installed
        # helper may be the previous one, so name the step that works with any of them.
        print('HELPER_PERMISSION_DENIED: ' + RERUN_ELEVATED_HINT)
        sys.exit(3)


if __name__ == '__main__':
    main()
