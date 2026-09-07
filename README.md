# ilson-box — 에이전트 박스 (v0)

고객 맥미니에 `ilson init --code XXXX-XXXX` 한 줄로 깔리는 것들. 설계서:
`coldbyte-vault/wiki/plans/2026-09-05-ilson-init-원커맨드-온보딩-설계.md`

```
ilson-box/
├── install.sh            고객이 붙여넣는 한 줄 (curl | sh) — CLI + template 을 ~/.ilson-cli 로
├── docs/                 고객용 문서 (설치.md · 사용법.md)
├── ilson                 CLI (doctor · init · pair · update)
├── template/             init 이 $ILSON_HOME 으로 복사하는 박스 골격
│   ├── CLAUDE.md         박스 안 Claude 의 행동 규칙 (한국어, 사장님 호칭, 발송 불가침)
│   ├── claude/           ~/.claude 에 들어갈 settings.json + commands/*.md (브리핑·주간·정리·온보딩)
│   ├── vault/            옵시디언 볼트 틀 (CONTEXT.md · company · journal · lessons · reports)
│   ├── lib/              launchd 가 부르는 셸 (run-job · notify · snapshot · watchdog · update)
│   └── launchd/          plist 틀 + jobs.conf (6개 예약 업무)
└── .sandbox/             시험용 ILSON_HOME (gitignore)
```

## 기존 시스템 무영향 계약

- `ilson init --sandbox` 는 `$ILSON_HOME` 아래에만 쓴다. `sudo`·`pmset`·`launchctl`·`~/.claude`·`~/Library/LaunchAgents` 는 건드리지 않는다.
- 실제 기계 세팅(1단계)·launchd 적재(8단계)는 `--sandbox` 없이, **새 맥미니 또는 새 macOS 계정**에서만.
- `ilson doctor` 는 항상 읽기 전용.

## 배포 (install.sh)

고객이 보는 것은 한 줄이다. 주소는 아직 미정 — `install.sh` 맨 위 `ILSON_DIST_BASE` 만 채우면 된다.

```bash
curl -fsSL https://<주소>/install.sh | sh
curl -fsSL https://<주소>/install.sh | sh -s -- --code ABCD-1234   # 설치 후 init 까지
```

설치기는 `sudo` 를 쓰지 않는다. `~/.ilson-cli` 에 CLI+template 를 두고 `~/.local/bin/ilson` 로 링크하며,
PATH 가 없으면 `~/.zprofile` 에 한 줄 붙인다. CLI 자리(`~/.ilson-cli`)와 박스 자리(`~/ilson`)는 반드시 다르다 —
같으면 `init` 이 CLI 를 덮어쓴다. 설치기가 그 경우를 막는다.

배포 묶음은 **git 에서** 만든다. `.sandbox/`·`.moai/` 가 고객 기계로 새어 나가지 않게:

```bash
git archive --format=tar.gz --prefix=ilson/ -o ilson-latest.tar.gz HEAD:ilson-box
```

## 시험

```bash
# CLI 만
ILSON_HOME=$PWD/ilson-box/.sandbox ./ilson-box/ilson init --code TEST-0000 --sandbox
ILSON_HOME=$PWD/ilson-box/.sandbox ./ilson-box/ilson doctor

# 설치기까지 (가짜 HOME 으로 격리 — 실제 홈은 안 건드린다)
FAKE=$(mktemp -d)
HOME=$FAKE ILSON_SRC=$PWD/ilson-box sh ilson-box/install.sh --code TEST-0000 --sandbox
```
