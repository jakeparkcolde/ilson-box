# 일손 Box — 맥미니 AI 비서

`~/ilson`에 회사 볼트와 Claude 기반 예약 업무를 구성합니다. CLI 설치만 끝내지 않고 필요한 도구와 박스 골격까지 준비합니다.

## 새 맥미니 설치

```sh
curl -fsSL https://raw.githubusercontent.com/jakeparkcolde/ilson-box/main/install.sh | sh
```

이미 설치한 맥에서도 같은 명령으로 CLI와 기본 구성을 갱신합니다. 기존 회사 노트와 연결 설정은 보존합니다. 로컬 체크아웃을 설치할 때는:

```sh
ILSON_SRC="$PWD" sh install.sh
```

자동 처리: Homebrew(없으면 관리자 입력 필요), git·jq·gh·coreutils, Claude Code·Codex CLI, Obsidian·Tailscale, Tavily CLI(없으면 uv로 격리 설치), `~/ilson` 볼트와 일손 검색 스킬·업무 스크립트, 예약 업무 plist 6개 생성. 기존 설치 도구는 재사용합니다. 기존 Orca는 그대로 사용하며 자동 설치 대상이 아닙니다.

사람이 할 일: 구독 계정 로그인, Tailscale 연결, 회사 인터뷰, 필요한 macOS 권한 클릭. Aside는 브라우저 업무를 사용할 때 별도로 연결합니다. 설치코드 없이 로컬 구성이 가능하며 서버 페어링은 아직 구현되지 않았습니다.

```sh
# 새 터미널을 열고 실행. PATH가 아직 반영되지 않았다면 ~/.ilson-cli/ilson 사용
ilson setup                       # 중단된 설치를 다시 실행
ilson setup --configure-machine   # 잠자기 방지·정전 후 재시작 (관리자 비밀번호)
cd ~/ilson
claude /onboard                   # 로그인·폴더 신뢰·회사 인터뷰
ilson start                      # 준비 확인 후 예약 업무 가동
ilson doctor                     # 읽기 전용 점검
```

Codex는 `codex`를 실행해 별도로 ChatGPT 계정에 로그인합니다. 현재 Box의 정기 업무 실행기는 Claude입니다. 설치기는 API 키나 유료 API 호출을 설정하지 않습니다.

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

- `setup`은 파일을 준비하고 예약 업무를 **새로 가동하지 않습니다**. `start`가 Claude 로그인, 폴더 신뢰, 회사명, 시간 제한 도구를 확인한 뒤 launchd에 등록합니다.
- `setup` 재실행은 기존 볼트 노트·연결 설정을 보존합니다. 관리 대상인 실행 스크립트와 Claude 규칙은 갱신합니다. 이미 실행 중인 서비스는 재시작하지 않습니다.
- FileVault·화면 잠금·자동 로그인·SSH 설정을 자동 변경하지 않습니다. FileVault가 켜진 기기는 재부팅 후 사람이 로그인해야 사용자 예약 업무가 재개됩니다.
- Tailscale 상태 조회는 최대 10초로 제한합니다. 로그인/초기화/기기 승인 대기, 연결 꺼짐, 온라인 확인, 조회 불가를 구분합니다. 대기나 CLI 조회 오류로 기본 설치를 실패 처리하지 않으며, 원격 연결 완료로도 표시하지 않습니다. 기존 연결을 변경하는 명령은 호출하지 않습니다.
- 텔레그램 설정이 없으면 보고서는 볼트에 저장되고 전송은 생략됩니다. 이를 알림 전송 성공으로 설명하지 않습니다.
- `doctor`는 원격 연결이 확인되지 않으면 진단 미완료로 종료 코드 1을 반환합니다. 이는 `setup`의 기본 설치 실패와 별개입니다. 점검 통과도 실제 보고 생성·알림 전송·재부팅 복구 시험을 대신하지 않습니다.

## 설치 옵션과 구조

- `sh install.sh --cli-only`: CLI만 설치 (이전 기본 동작).
- `ILSON_SRC=/경로 sh install.sh`: 로컬 소스 또는 tar.gz 설치.
- `ILSON_SOURCE_REF=<커밋> sh install.sh`: GitHub 소스 리비전 지정.
- `ilson setup --sandbox`: `$ILSON_HOME` 안에만 박스 구성. 도구 설치·로그인·sudo·launchctl·알림 발송 없음. 샌드박스에서는 `start`도 거부합니다.
- `ilson pair --code <코드> --pairing-file <로컬파일>`: 별도 준비한 연결 정보를 로컬에 저장. 서버 등록 명령이 아닙니다.
- CLI: `~/.ilson-cli`, 명령 링크: `~/.local/bin/ilson`, 박스: `~/ilson`.

## 검증

```sh
python3 -m unittest discover -s tests -v
bash -n ilson
sh -n install.sh
```

시험은 임시 폴더와 가짜 명령을 사용하며 호스트 서비스·전원·계정·앱을 변경하지 않습니다. 실제 신규 맥미니 설치와 재부팅은 별도 검증 대상입니다.
