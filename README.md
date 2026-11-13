# 일손 Box — 맥미니 AI 비서

`~/ilson`에 회사 볼트와 Claude 기반 예약 업무, 이 맥의 웹 관리자를 함께 구성합니다. 설치가 끝나면 브라우저에서 설정 안내·업무 상태·보고서를 확인할 수 있습니다.

## 11/9 강의 키트

새로 설치하면 Box 폴더의 `강의키트-20261109-v2`에 시작 자료가 생깁니다. 기존 설치는 업데이트를 받은 뒤 `ilson course-kit`을 실행해 새 예시를 받으세요. 이전 `강의키트-20261109`와 새 폴더의 기존 파일, 볼트는 보존합니다. `시작과_막힘_복구.md`에서 기기별 경로와 문서 실습을 확인하세요. 키트의 노션 링크는 강사가 공개하기 전에는 열리지 않을 수 있습니다.

## 새 맥미니 설치

macOS 13 이상에서 Apple Silicon과 Intel을 구분해 점검합니다. Intel 전체판은 Homebrew 의존 도구 지원을 별도로 확인해야 하며, 강의에서는 강의판(Claude Code + Orca + Obsidian + 위키 + 자동 스킬)을 권장합니다. Intel 강의판은 터미널에서 `curl -fsSL https://raw.githubusercontent.com/jakeparkcolde/ilson-box/main/course/install-intel-mac.sh | bash` 로 설치합니다(macOS 13 이상). Windows 10·11은 PowerShell에서 `irm https://raw.githubusercontent.com/jakeparkcolde/ilson-box/main/course/install-windows.ps1 | iex` 로 설치합니다.

```sh
curl -fsSL https://raw.githubusercontent.com/jakeparkcolde/ilson-box/main/install.sh | sh
```

업데이트는 주소를 정하지 않아도 공개 배포(GitHub Releases)에서 받습니다. 별도 주소를 쓰거나 박스를 다른 배포로 옮길 때만 설치할 때 함께 넣거나, 나중에 `ilson update --feed <주소>`를 한 번 실행합니다.

```sh
curl -fsSL https://raw.githubusercontent.com/jakeparkcolde/ilson-box/main/install.sh | sh -s -- --feed <주소>
```

이미 설치한 맥에서도 같은 명령으로 CLI와 기본 구성을 갱신합니다. 기존 회사 노트와 연결 설정, 저장된 업데이트 주소는 보존합니다. 로컬 체크아웃을 설치할 때는:

```sh
ILSON_SRC="$PWD" sh install.sh
```

자동 처리: Homebrew(없으면 관리자 입력 필요), git·jq·gh·coreutils·Python·Node.js, Claude Code·Codex CLI, Herdr Desktop·hc, Aside 브라우저·CLI, Obsidian·Tailscale, Tavily CLI(없으면 uv로 격리 설치), `~/ilson` 볼트와 일손 검색 스킬·업무 스크립트, 예약 업무 plist와 강의 키트 생성. 기존 설치 도구는 재사용합니다. 기존 Orca는 그대로 사용하며 자동 설치 대상이 아닙니다.

사람이 할 일: 구독 계정 로그인, Tailscale 연결, 회사 인터뷰, 필요한 macOS 권한 클릭. Herdr와 Aside를 열어 필요한 계정에 직접 로그인하고 연결합니다. 설치코드 없이 로컬 구성이 가능하며 서버 페어링은 아직 구현되지 않았습니다.

기본 설치 중 텔레그램 알림 연결도 안내합니다. BotFather가 발급한 토큰을 숨김 입력창에 붙여넣고, 열리는 텔레그램에서 **시작**을 누르면 받을 개인 대화를 자동으로 찾습니다. 나중에 연결할 수도 있고, 재설치 때는 기존 연결을 보존합니다.

```sh
# 새 터미널을 열고 실행. PATH가 아직 반영되지 않았다면 ~/.ilson-cli/ilson 사용
ilson setup                       # 중단된 설치를 다시 실행
ilson setup --configure-machine   # 잠자기 방지·정전 후 재시작 (관리자 비밀번호)
cd ~/ilson
claude /onboard                   # 로그인·폴더 신뢰·회사 인터뷰
ilson start                      # 준비 확인 후 예약 업무 가동
ilson doctor                     # 읽기 전용 점검
ilson open                       # 내 일손 웹 관리자 열기
ilson admin status               # 웹 관리자 실행 상태 확인
ilson chat                       # 이후 설치·설정·업무 요청을 하는 관리 대화
ilson telegram connect           # 텔레그램 알림 연결·변경을 다시 시작
ilson telegram status --verify   # 봇과 받을 대화 확인 (메시지 발송 없음)
```

Codex는 `codex`를 실행해 별도로 ChatGPT 계정에 로그인합니다. 현재 Box의 정기 업무 실행기는 Claude입니다. 설치기는 API 키나 유료 API 호출을 설정하지 않습니다.

설치가 막히면 `ilson doctor --install --share`로 로컬 지원 파일을 만드세요. 라이선스와 네트워크 없이 동작하며 자동 전송하지 않습니다. 일손/Python 없는 독립 진단과 고정 SHA 설치 명령 생성, 현재 창·새 창 확인은 [설치 진단 안내](docs/install-diagnostics.md)를 참고하세요. 이 소스의 진단 기능은 공개 배포 승인 전입니다.

## 기본 웹 관리자

기본 설치가 웹 관리자 서비스를 준비하고 브라우저를 엽니다. 이후 `ilson open` 또는 `~/ilson/일손 열기.command`를 두 번 눌러 엽니다. 관리자 서비스는 로그인 시 시작하며 예약 업무를 새로 가동하지 않습니다.

화면은 기존 일손과 같은 디자인을 사용합니다. 다크 모드가 기본이며 라이트 모드로 전환할 수 있습니다. 테마 선택은 다음에 열 때도 유지됩니다. 글꼴도 설치본에 포함해 외부 글꼴 서비스 없이 표시합니다.

- **홈·설정 안내:** 회사 정보와 AI 로그인·폴더 신뢰·알림 연결 상태, 아직 필요한 단계의 명령을 확인합니다. 로그인과 회사 인터뷰는 본인 터미널에서 진행합니다.
- **자동화·컴퓨터 현황:** CPU·메모리·설치 볼륨의 디스크 사용량과 일손 업무, 현재 사용자의 다른 launchd 등록을 읽기 전용으로 확인합니다. 실행 PID·종료값과 업무 성공 도장을 구분하며 수집 실패·지난 관측·빈 목록을 표시합니다. [관측 범위와 설치 안내](docs/resource-dashboard.md)를 참고하세요.
- **내 업무:** 등록된 업무 일정, 현재 등록 여부, 기록된 마지막 성공 시각을 확인합니다. 현재 실행 중인지와 실패 이력을 아직 계측하지 못한 경우 확인되지 않았다고 표시합니다.
- **보고서:** 이 Box의 `vault/reports/` 아래 Markdown 보고서를 읽습니다. 보고서 내용은 실행하지 않으며 본문에 있는 HTML도 글자로 표시합니다.
- **연결:** 텔레그램 설정 여부와 별도 확인이 필요한 상태를 구분합니다. 관리 화면을 여는 것만으로 메시지나 LLM 요청을 보내지 않습니다.

첫 버전은 이 맥에서만 접속하는 조회·설정 안내 화면입니다. 웹에서 업무를 실행하거나 일정을 바꾸는 기능, 중앙 일손의 리서치·교육 설문·팩 설치, 휴대폰 외부 접속은 포함하지 않습니다. 업무 설정은 `ilson chat` 또는 안내된 명령으로 진행합니다.

`127.0.0.1:18794`를 기본 사용하며 포트가 이미 사용 중이면 다른 서비스를 종료하지 않고 안내합니다. `ilson open --port 18795`처럼 별도 포트를 선택할 수 있습니다. 관리자 인증 정보는 `state/web-admin/`의 제한된 파일에 두고 Git 백업·화면·로그에서 제외합니다. 접속 주소를 직접 입력해 인증이 풀렸다면 `ilson open`으로 다시 여세요. 인터넷 공개나 Tailscale 설정 변경은 하지 않습니다.

```sh
ilson admin stop    # 관리 화면 서비스만 중지. 예약 업무는 계속 동작
ilson admin start   # 브라우저를 열지 않고 관리 화면 서비스 시작
ilson open         # 중지된 관리자를 복구하고 화면 열기
```

## 기본 웹 검색

검색 기준은 기기에서 수동 설치한 상태가 아니라 이 저장소의 설치 코드와 템플릿으로 배포합니다.
`setup`은 Tavily CLI와 `.claude/skills/ilson-search/SKILL.md`, `lib/search.sh`를 함께 준비합니다.
검색 실행은 1회당 basic·최대 5건·45초로 제한합니다. 스킬은 업무당 최대 3회와 출처/조회일 표시를 지시합니다.
업무당 횟수는 스킬 지침이며 계정 전체의 과금 상한을 강제하는 기능은 아닙니다.

```sh
ilson doctor --probe-search  # 공개 검색 1회, 계정이 연결돼 있으면 크레딧 사용 가능
tvly login                  # 예약 검색용 인증은 새 맥의 일반 터미널에서 직접
```

일반 `doctor`는 검색 파일·실행 파일만 확인하고 실제 검색 미확인을 표시합니다.
무인증 검색은 제한이 있으며 인증 완료·남은 한도를 보장하지 않습니다.
기존 운영 기기의 인증을 복사하지 않고 각 기기의 계정을 사용합니다. 설치 중 `tvly init`이나 전역 스킬 변경은 하지 않습니다.
기본 아침 브리핑에는 자동으로 외부 검색을 추가하지 않습니다. 검색할 주제와 일정을 정하면 해당 업무에 연결합니다.
전체 도구 갱신은 위 설치 명령을 재실행합니다. 기존 `ilson update`는 Tavily 의존성까지 설치하는 경로가 아닙니다.
설치 기준과 인세인서치 검토는 [검색 구성](docs/검색-구성.md)을 참고하세요.

## 동작 경계

- 대화형 `ilson chat`은 Claude `auto` 모드로 시작합니다. 설치·설정·일정 등록까지 요청 범위에서 처리하고, curl 일괄 금지와 볼트 밖 편집 금지는 제거했습니다. 자동 심사는 모든 작업을 무조건 허용하는 기능이 아니며, 미지원 환경에서 권한 우회 모드로 자동 전환하지 않습니다.
- 예약 LLM 업무는 별도 `lib/job-settings.json`과 `job-rules.md`를 사용합니다. 사용자/프로젝트/local 설정을 제외하고 `dontAsk`, 명시적인 도구 목록, MCP 제외, safe-mode로 실행합니다. 구독 로그인을 유지하며, 관리 권한·개인 플러그인·훅을 재사용하지 않습니다. 조직 관리 정책은 여전히 적용됩니다.
- 설치와 전원 설정에 필요한 관리자 인증, 고객 발송·결제·대량 삭제·계정/보안 변경의 확인은 남깁니다. 발행·결제 확인은 현재 행동 규칙과 Claude 심사에 의존하며 모든 셸/API 경로를 막는 독립 게이트는 아닙니다. 권한 분리는 OS 격리가 아니므로 이 맥에는 업무에 필요한 계정만 연결하는 것을 권장합니다.
- 기존 Claude 대화는 종료하고 새 설치 후 `ilson chat`으로 다시 시작해야 새 규칙/모드가 확실히 반영됩니다. 다른 설정 파일의 deny/조직 정책은 설치기가 임의 삭제하지 않습니다.

- `setup`은 웹 관리자를 준비하고 예약 업무는 **새로 가동하지 않습니다**. `start`가 Claude 로그인, 폴더 신뢰, 회사명, 시간 제한 도구를 확인한 뒤 예약 업무를 launchd에 등록합니다.
- `setup` 재실행은 기존 볼트 노트·연결 설정·사용자 예약 설정을 보존합니다. 관리 대상인 실행 스크립트와 Claude 규칙·웹 화면은 갱신합니다. 사용자 추가 명령은 별도 이름으로 유지하세요. 실행 중인 예약 업무는 재시작하지 않으며 웹 관리자만 서버·화면이 바뀌었을 때 갱신합니다.
- FileVault·화면 잠금·자동 로그인·SSH 설정을 자동 변경하지 않습니다. FileVault가 켜진 기기는 재부팅 후 사람이 로그인해야 사용자 예약 업무가 재개됩니다.
- Tailscale 상태 조회는 최대 10초로 제한합니다. 로그인/초기화/기기 승인 대기, 연결 꺼짐, 온라인 확인, 조회 불가를 구분합니다. 대기나 CLI 조회 오류로 기본 설치를 실패 처리하지 않으며, 원격 연결 완료로도 표시하지 않습니다. 기존 연결을 변경하는 명령은 호출하지 않습니다.
- 텔레그램 설정이 없으면 보고서는 볼트에 저장되고 전송은 생략됩니다. 이를 알림 전송 성공으로 설명하지 않습니다.
- 텔레그램 연결은 예약 보고·알림을 받을 통로입니다. 텔레그램에서 업무를 지시하는 수신 기능은 포함하지 않습니다. 토큰은 이 기기에 권한 0600으로 저장하며 연결 화면·명령 인자·회사 노트에 기록하지 않습니다. 다른 프로그램이 사용하는 봇의 webhook이나 수신 설정을 자동 변경하지 않습니다.
- `doctor`는 원격 연결이 확인되지 않으면 진단 미완료로 종료 코드 1을 반환합니다. 이는 `setup`의 기본 설치 실패와 별개입니다. 점검 통과도 실제 보고 생성·알림 전송·재부팅 복구 시험을 대신하지 않습니다.

## 설치 옵션과 구조

- `sh install.sh --cli-only`: CLI만 설치 (이전 기본 동작).
- `ILSON_SRC=/경로 sh install.sh`: 로컬 소스 또는 tar.gz 설치.
- `ILSON_SOURCE_REF=<커밋> sh install.sh`: GitHub 소스 리비전 지정.
- `sh install.sh --feed <주소>`: 별도 업데이트 주소를 `~/ilson/.updates/feed`에 저장. `ILSON_UPDATE_FEED`로도 줄 수 있습니다. 이미 저장된 주소는 `--feed`를 줄 때만 바꿉니다. 주소가 없으면 공개 기본 주소를 씁니다.
- `ilson setup --sandbox`: `$ILSON_HOME` 안에만 박스 구성. 도구 설치·로그인·sudo·launchctl·알림 발송 없음. 샌드박스에서는 `start`도 거부합니다.
- `ilson pair --code <코드> --pairing-file <로컬파일>`: 별도 준비한 연결 정보를 로컬에 저장. 서버 등록 명령이 아닙니다.
- `ilson update`는 배포에 포함된 CLI 파일(`ilson`, `template/`, `tools/update.py`)과 박스 코드를 함께 갱신합니다. 도구 설치나 텔레그램 연결 같은 기본 구성 단계는 다시 하지 않으므로, 그런 단계가 필요한 기능은 맨 위 설치 명령을 다시 실행합니다. 이미 설치된 관리자는 코드·화면 갱신 후 서비스를 갱신합니다.
- CLI: `~/.ilson-cli`, 명령 링크: `~/.local/bin/ilson`, 박스: `~/ilson`.

## 검증

```sh
python3 -m unittest discover -s tests -v
bash -n ilson
sh -n install.sh
```

시험은 임시 폴더와 가짜 명령을 사용하며 호스트 서비스·전원·계정·앱을 변경하지 않습니다. 실제 신규 맥미니 설치와 재부팅은 별도 검증 대상입니다.

권한 분리 시험은 실행 인자·프로필 배포·실패 처리·설정 보존을 검증합니다. 실제 Claude의 auto 가용성, 예약 모드의 볼트 쓰기/검색 허용, 승인 요청 동작은 새 맥에서 별도 확인해야 합니다. 예약 실행에서 도구 권한이 거절되면 성공으로 기록하지 않습니다.

## 배포 코드 안전 업데이트

`ilson update`로 관리자·공용 도구·리서치의 배포 코드를 갱신합니다. `ilson update --check`는 확인만 하고, `ilson update --rollback`은 직전 코드를 복구합니다. 운영 데이터·로그인 정보·설정·예약 파일은 그대로 두며, 수정된 관리 파일이 있으면 덮어쓰지 않고 중단합니다.

새로 설치한 맥은 주소를 정하지 않아도 공개 배포(GitHub Releases)에서 `ilson update`와 매일 09:30 자동 업데이트를 받습니다. 별도 주소를 쓰거나 박스를 다른 배포로 옮길 때만 설치할 때 `--feed <주소>`를 넣거나, 설치 후 `ilson update --feed <주소>`를 한 번 실행하세요. `ILSON_UPDATE_FEED=<주소> ilson update`처럼 환경 변수로 줘도 됩니다. 실제 실행이 한 번 성공하면 쓴 주소를 `~/ilson/.updates/feed`에 기억하므로 CLI를 다시 설치해도 유지됩니다. 이미 다른 주소를 쓰는 맥은 다시 설치해도 그 주소를 그대로 쓰므로, 공개 배포로 옮길 때는 `ilson update --feed https://github.com/jakeparkcolde/ilson-box/releases/latest/download/latest-v2.json`를 한 번 실행합니다.

배포 절차는 [통합 업데이트 운영 기준](docs/integrated-update/OPERATIONS-2026-10-13.txt), 지난 적용 기록은 [안전 업데이트 기록](docs/safe-update/HANDOFF-2026-10-13.md)을 참고하세요.

실행 중인 작업은 자동 재시작하지 않습니다. 관리자는 `ilson open`, 리서치는 `ilson research`로 다시 열면 설치한 코드를 사용합니다. 공개 배포는 Tailscale 연결이 필요 없습니다. 별도 주소가 Tailscale 안에 있을 때만 필요합니다.

## 직원·조직도·업무 스킬

기존 관리자 셸의 **직원 / 조직도 / 업무 스킬**에서 부서별 프로필·드래그 조직도·유형별 스킬을 관리합니다. 직원에게 문서 작성·리서치·지식 수집을 맡기고 실제 결과·적용 지침을 확인하며, 기존 설치 정기업무의 담당을 연결할 수 있습니다. [사용법과 지원 범위](docs/직원-조직도-스킬.md)를 참고하세요.

## 반복 업무와 배운 점

`ilson learn enable`로 직접 켠 뒤 새 `ilson chat`을 열면, 완료한 업무가 반복될 때 스킬 초안을 제안하고 수정·실패·성공에서 배운 기준의 변경안을 준비합니다. `ilson learn proposals`와 `ilson learn show <ID>`로 확인하고, 사람이 일반 터미널에서 `ilson learn approve <ID>`를 실행한 것만 반영합니다. `reject`는 거절, `history`와 `rollback <변경ID>`는 변경 확인과 복구입니다. [자세한 사용법](docs/사용법.md)을 참고하세요.

자동 관찰은 대화 모델이 지침을 따르는 범위이며 빠뜨릴 수 있습니다. 회사·고객 이름이나 비밀은 업무 이름과 초안에서 빼고 승인 전 직접 확인하세요. 검사로 모든 개인정보를 찾을 수는 없습니다. 기록과 초안은 이 Box의 볼트 및 로컬 Git 이력에 남을 수 있고, Claude·Codex 대화는 해당 제공자의 처리를 받습니다. 이 기능은 별도 LLM 호출이나 텔레그램 발송을 추가하지 않습니다. 정기 업무와 직원 화면의 지침에는 반복 감지가 자동 연결되지 않습니다.

### 로컬 지식 큐레이터

`ilson curator` (`ilson diary`)는 외부 AI·네트워크 없이 하루 변경 기록·기존 태그/내부 링크로 연결된 노트·명시적인 확인 항목을 새 `vault/journal/curator/YYYY-MM-DD.md`에 모읍니다. 강의판은 선택한 볼트 바로 아래 `journal/curator/`입니다. 기존 노트·색인·기존 결과의 바이트와 mtime을 바꾸지 않습니다. 같은 날짜는 한 번만 생성하고, 수동 `--addendum`은 별도 새 파일을 만듭니다. 임시 문서는 출력 파일시스템의 비공개 `.staging/`에 두고 원자적으로 독점 게시합니다.

최초 OFF입니다. 일반 터미널에서 입력 범위·저장 위치를 읽고 동의하거나 `ilson curator --on`으로 동의만 저장하세요. `--off`는 이후 읽기를 막고 진행 중인 로컬 작업의 종료를 기다립니다. `--status`와 `--off`는 라이선스 없이 쓸 수 있습니다. 정리 실행은 유효한 로컬 라이선스 캐시만 확인하며 서버 재확인이 필요하면 본문을 읽기 전에 보류합니다. 별도 `ilson license status`는 서버에 접속할 수 있습니다. AI 요약은 비활성화되어 있고 전송 구현도 없습니다.

입력은 `company/**/*.md`, `journal/YYYY-MM-DD.md`, `reports/briefing/*.md`, `reports/weekly/*.md`입니다. 파일당 256 KiB·실행당 100개/2 MiB를 넘거나 읽기에 실패한 자료는 누락 개수를 표시합니다. 숨김·관리/개인 영역·미승인 학습·승인 대기·첨부·설정·대화 원문·링크/하드링크·자기 출력은 제외합니다. 현재 단일 사용자용이며 다계정 공유 볼트 권한 기능은 제공하지 않습니다.

Mac 전체판은 `--auto-on`을 별도로 켜고 기존 watchdog이 실제 가동 중이어야 현지시각 23:00부터 약 10분 오차로 정리합니다. 새 launchd 작업과 jobs.conf 항목은 추가하지 않습니다. 놓친 날짜는 가장 최근 한 번만 보충하며 시계 역행·시간대 변경에는 보류합니다. `--status`가 `watchdog_compatible: false`이면 기존 watchdog을 재설치/검토해야 합니다. start 전이나 예약이 꺼진 상태를 자동 가동이라고 안내하지 않습니다. Windows·Intel 강의판은 수동 전용이며 `--auto-on`은 예약 미지원을 반환합니다.

강의 도우미의 첫 갱신은 검수한 고정 버전 설치기 재실행입니다. 이후 `ilson update --manifest <검수한 고정 JSON>` 또는 `--source-ref <40자리 커밋> --sha256 <해당 판본 설치기 SHA-256>`으로 같은 설치기에서 도우미 payload만 검증·백업·교체·자체 점검합니다. 고정 정보가 없으면 갱신하지 않으며, 저장한 고정 정보는 `ilson update`에 재사용합니다. main 자동 추적은 하지 않습니다. `ilson curator --off` 후 `ilson update --rollback`은 직전 코드 백업만 복구하고 사용자 노트·설정·실행기·Python 선택·PATH는 보존합니다. 배포용 고정 JSON은 `python3 tools/build_course_update.py --source-ref <검수 커밋> --edition intel-course` (Windows는 `windows-course`)로 만들 수 있습니다. 이 작업은 파일 생성만 하며 공개·배포는 별도 승인입니다.
