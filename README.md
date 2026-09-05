# ilson-box — 에이전트 박스 (v0)

고객 맥미니에 `ilson init --code XXXX-XXXX` 한 줄로 깔리는 것들. 설계서:
`coldbyte-vault/wiki/plans/2026-09-05-ilson-init-원커맨드-온보딩-설계.md`

```
ilson-box/
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

## 시험

```bash
ILSON_HOME=$PWD/ilson-box/.sandbox ./ilson-box/ilson init --code TEST-0000 --sandbox
ILSON_HOME=$PWD/ilson-box/.sandbox ./ilson-box/ilson doctor
```
