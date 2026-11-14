# 회사 Mac 한 대 · 대표와 직원 사용 안내

2026-11-14 · 2기 파일 접근 범위 · 실제 두 계정 리허설 후 운영 적용

> 회사 맥미니는 한 대지만 접속 계정은 각자 사용합니다. Windows에서 연결할 때도 본인의 Mac 사용자 이름과 SSH 키를 쓰고, Claude는 본인 계정으로 로그인합니다. 회사 자료는 함께 보고 개인 자료는 각자의 공간에 보관합니다. 설치·예약 업무·승인·관리 화면은 대표가 담당합니다. 직원에게 대표 비밀번호나 관리자 접속 링크를 공유하지 않습니다.

## 먼저 정할 담당과 기본값

대표와 직원은 **macOS 계정**입니다. 관리 화면의 기존 ‘직원’ 기능에 만든 AI 직원/프로필은 macOS 사용자나 보안 권한이 아닙니다. `company init`의 불변 ID와 OS UID가 사람을 연결합니다. 표시 이름이나 환경 변수로 다른 사람 행세를 할 수 없습니다.

D-a: 직원은 company에 직접 쓸 수 있습니다. 대표 runtime의 `state/company-history/repository`에 공용 자료만 Git 이력으로 보관합니다. 주기 사이 변경이나 아직 스냅샷되지 않은 변경까지 보장하는 실시간 저장 이력은 아닙니다. `git log -- company`로 검토하고 복구본을 확인한 뒤 공용 파일을 복원합니다. 전체 runtime의 옛 `.git`을 공유 폴더에 옮기지 않습니다.

D-b: people의 각 폴더는 본인 전용입니다. 대표의 일반 세션도 타인 개인 영역을 읽지 않습니다. root/시스템 관리자, 사용자가 스스로 공용 폴더에 복사하는 행위까지 막는 DLP는 아닙니다. 퇴사 이관은 명시 명령만 수행합니다.

D-c: 기존 대표 Box의 기기 라이선스 하나를 유지합니다. 직원 연결에서 새 device-id를 만들거나 대표 시리얼·인증을 복사하지 않습니다. 사람별 좌석 과금은 현재 없습니다.

D-d: 웹 관리자와 Telegram 승인 수신기는 대표 전용입니다. 직원에게 현재 token/접속 링크를 주면 안 됩니다. 직원의 웹 로그인·웹 편집은 이번 범위가 아닙니다.

D-e: 현장 설치·재부팅 복구 담당 이름과 연락 방법은 아래 점검표에 직접 정합니다. 코드가 담당자를 자동 지정하지 않습니다. D-a~d 계약은 `template/lib/access_policy.py`의 `DEFAULTS` 한 곳에 모여 있습니다. 다른 정책으로 바꿀 때는 ACL 계획과 테스트도 함께 검토합니다.

## 대표가 할 일

1. macOS에서 대표 계정과 **표준 직원 계정**을 미리 준비합니다. 공용 Homebrew·앱 설치 담당은 한 명입니다. brew 소유권을 번갈아 바꾸거나 직원이 전체 설치기를 다시 실행하지 않습니다.
2. 대표가 기존 Box의 설치·라이선스·Claude 로그인·GUI 최초 로그인·TCC/Keychain 상태를 확인합니다. 직원에게 대표 home 전체나 runtime을 공유하지 않습니다.
3. 다음은 예시 ID입니다. 영어 소문자로 시작하는 불변 ID와 실제 Mac 계정명으로 바꿉니다. UID는 명령이 macOS 계정에서 조회합니다.

```sh
ilson company init --id acme --owner owner:owneraccount --staff worker:workeraccount --dry-run
ilson company init --id acme --owner owner:owneraccount --staff worker:workeraccount --apply
ilson company status
ilson doctor
```

계획에는 회사 전용 그룹, 사용자 가입, 루트·개인·관리 폴더, 상속 ACL, 직원 읽기 전용 연결 도구, 대표 runtime 비공개 설정이 표시됩니다. `--apply`는 터미널에서 `yes`를 입력한 뒤 정상 macOS 관리자 인증 창을 엽니다. 암호를 명령/파일/채팅에 넣지 마세요. 계정 생성과 Remote Login 설정은 자동 실행하지 않습니다. 기존 회사 경로가 있으면 초기화하지 않고 중단합니다. 적용 중 실패했다면 생성된 그룹·폴더·config 존재 여부를 현장 담당자가 확인해야 하며 자동 삭제/재초기화하지 않습니다.

기존 노트는 원래 볼트에 남아 있습니다. **공용 CONTEXT도 자동 공개하지 않습니다.** 다음 목록을 작성해 백업과 목적지를 검토하고 대표가 승인한 파일만 복사합니다. 읽기/쓰기 링크는 만들지 말고 일반 파일을 복사합니다. 원본과 기존 `.git`은 대표 비공개 위치에 보존합니다.

| 기존 상대 경로 | 목적지 | 공개 범위 | 원본/백업 확인 | 대표 확인 |
|---|---|---|---|---|
| `vault/CONTEXT.md` | `company/CONTEXT.md` (공개 내용만) | 회사 | 미확인 | 미승인 |
| `vault/company/...` | `company/...` 또는 `management/...` | 파일별 결정 | 미확인 | 미승인 |
| `vault/journal/...`, `vault/reports/...` | 기본 `management/...`, 공개는 별도 선택 | 파일별 결정 | 미확인 | 미승인 |
| 개인 문서 | `people/본인ID/...` | 본인 | 미확인 | 미승인 |

회사 자동화는 새 위치만 사용합니다. 이관 전에는 회사 정보와 보고 자료가 비어 보일 수 있습니다. 회사 소개 준비 후 대표 계정에서 기존 `ilson start`를 사용합니다. 회사의 코드 업데이트도 대표만 실행합니다. 공유 직원 도구는 초기 구성 때의 검수된 복사본이며 대표 코드 업데이트가 직원 도구를 자동 교체하지 않습니다. 새 회사 기능 배포 시 공유 client 갱신은 현장 담당자가 버전·계획을 검토해 별도 적용해야 합니다.

## 직원이 할 일

자기 Mac 계정으로 접속한 터미널에서 실행합니다. 개인 전체 Box나 Intel 강의판을 중복 설치하지 않습니다.

```sh
/Users/Shared/Ilson/acme/client/ilson company join --id acme
export PATH="$HOME/.local/bin:$PATH"
cd "$HOME/.ilson-company/acme/workspace"
claude
```

이 연결은 개인 workspace 안내와 `~/.local/bin/ilson`만 준비합니다. 기존 ilson이 다른 설치를 가리키면 덮지 않고 중단합니다. Claude CLI와 필요한 공용 앱은 대표가 한 번 준비하고 직원은 자기 계정으로 Claude 인증·폴더 신뢰를 마칩니다. workspace의 CLAUDE.md에 공용·본인 개인 경로가 적힙니다. 실제 자료는 공유 볼트의 허용 폴더에서 읽고 씁니다. 대표 인증이나 license/token을 가져오지 않습니다.

`ilson curator --on`은 본인이 입력 범위를 읽고 동의해야 켜집니다. 공용 자료와 본인 개인 자료를 정리하며 출력은 `people/본인ID/journal/curator/`입니다. 개인 자동 예약은 지원하지 않습니다. `ilson doctor`로 회사 연결과 담당 구분을 확인합니다. `start/pause/resume/update/admin/setup`은 대표 전용 안내로 거절됩니다. 설치 진단은 각자의 home 아래 비공개 run만 사용하며 노트 본문을 수집하지 않습니다.

## 대표 예약·승인·공개

대표 AI 예약 업무는 `company/`와 `management/`의 허용된 Markdown 복사본만 비공개 임시 작업 폴더에서 읽습니다. `people/*`는 열거하거나 복사하지 않습니다. CLI의 `--restricted`(작업 폴더 제한), `--safe-mode`(CLAUDE.md/플러그인/훅 등 자동 주입 중지), 읽기 도구 Read/Glob/Grep만 허용합니다. Bash·MCP·직접 파일 쓰기·추가 디렉터리는 허용하지 않습니다. 이 옵션이 없는 CLI는 자동으로 넓은 권한으로 돌아가지 않고 중단합니다. OAuth를 끄는 `--bare`는 사용하지 않습니다.

보고서는 helper가 `management/reports/<업무>/<날짜>.md`에 새로 저장하며 기존 파일을 덮지 않습니다. Telegram에는 제목·본문·파일명 없이 고정 완료 문장만 갑니다. 기존 Bash/외부 웹 검색/쓰기 도구가 필요한 사용자 지정 업무는 이 제한으로 완료하지 못할 수 있습니다. 현재 회사 예약은 자료 기반 보고서 작성까지이며 발행/운영 작업은 대표가 별도 처리합니다. `tidy`는 동의된 공용 큐레이터만 실행합니다. 별도 로컬 주간 통계는 company의 일지 표시만 집계하고 private 승인·학습 DB를 합치지 않습니다.

대표 웹 관리자는 공용 보고와 관리 보고를 볼 수 있으며 직원 로그인은 없습니다. 서류함 원본·승인 초안/완료 기록은 management에 보관합니다. 회사 모드의 Telegram 승인 본문 카드는 막고 대표 웹에서 승인합니다. 학습은 대표 runtime의 별도 비공개 저장소를 사용하여 학습 초안·기준·스킬이 공용 보고에 자동 섞이지 않습니다.

공개할 보고서는 대표가 원문을 검토한 뒤 다음처럼 계획과 적용을 분리합니다.

```sh
ilson company publish management/reports/briefing/2026-11-14.md --to company/reports/공개브리핑.md
ilson company publish management/reports/briefing/2026-11-14.md --to company/reports/공개브리핑.md --apply
```

퇴사자 데이터는 자동 이동하지 않습니다. 먼저 해당 사람의 열린 SSH/Claude/편집 세션을 종료하고 자료 이관을 안내합니다. 열린 파일 핸들과 이미 복사한 데이터는 사후 회수할 수 없습니다.

```sh
ilson company offboard worker --dry-run
ilson company offboard worker --apply
```

명시 적용은 회사 그룹에서 제거하고 새 공용 접근을 거절한 뒤 개인 폴더를 `management/offboarding/worker/`로 옮깁니다. 옮긴 트리의 이전 직원 ACL/소유권은 대표 전용으로 정리합니다. 설정에서도 비활성 처리하며 이후 앱 접근은 거절됩니다. 동일 불변 ID를 새 직원에게 재사용하지 않습니다. 열린 세션의 그룹 캐시·열린 파일 핸들은 현장 점검과 세션 종료가 필요합니다.

## Windows에서 연결하기

같은 회사 tailnet에 각 사람을 초대합니다. 회사 Mac의 Tailscale 로그인/활성 tailnet은 담당 한 명이 관리합니다. 직원마다 다른 tailnet으로 Mac을 전환하지 않습니다. 여기서 SSH는 **Tailscale 위의 macOS Remote Login/OpenSSH**입니다.

Mac 시스템 설정의 Remote Login 허용 사용자를 대표와 해당 직원으로 제한합니다. 각 Windows PC에서 만든 개인 SSH 키의 공개키만 **자기 Mac 계정**에 등록합니다. 대표 키나 계정 암호를 공동 사용하지 않습니다. SSH/Herdr 터미널 접속은 Mac Obsidian·Aside GUI 화면을 제공하는 원격 데스크톱이 아닙니다. Windows `localhost`도 Mac의 관리자가 아닙니다. 대표 관리자 접속은 대표만 사용하는 SSH 터널과 기존 token으로 구성하며 직원에게 같은 연결을 제공하지 않습니다.

## 현장 설치·재부팅 리허설 체크리스트

- [ ] 현장 준비 담당 / 재부팅 복구 담당 / 대표 승인자 / 연락 방법 기록.
- [ ] 공유 brew/앱 담당 한 명, 대표·직원 OS 계정과 각자의 Claude 인증 확인.
- [ ] 대표 최초 GUI 로그인, 앱 최초 실행/TCC/Keychain 확인. 직원 GUI 필요 항목도 본인 계정에서 확인.
- [ ] 각 Windows에서 본인 SSH 키→본인 Mac UID 확인. Remote Login 허용 목록에 불필요한 사용자 없음.
- [ ] 회사 tailnet 연결과 빠른 사용자 전환 후 접근 확인. 타인의 tailnet을 끊지 않음.
- [ ] 직원 company 읽기/쓰기, 본인 people 읽기/쓰기, 타인 people·management·runtime 읽기/쓰기 거절.
- [ ] Obsidian atomic save, rename, 외부 파일 이동, symlink/hardlink, 상위 폴더 대체 시나리오. 적용 ACL은 이 개발 Mac에서 시험하지 않음.
- [ ] 회사 snapshot Git object·큐레이터·공용 보고·진단·Telegram에 개인/관리 sentinel 없음. 대표 AI 결과는 management에만 존재.
- [ ] 대표 AI 실제 CLI에서 people/원본 runtime/임시 폴더 밖 읽기 거절, Bash/MCP/쓰기 도구 없음. mock 테스트를 실기 통과로 간주하지 않음.
- [ ] 직원 start/pause/update 거절, 대표 watchdog/update/approval poller는 각 하나. 라이선스 기기 추가 등록 없음.
- [ ] 직원 로그아웃 후 대표 업무 정상. 대표 로그아웃 시 GUI LaunchAgents 중단을 안내하고 ‘계속 실행’으로 표시하지 않음.
- [ ] 화면 잠금/절전/빠른 전환/로그아웃을 구분. 재부팅→FileVault 해제→대표 GUI 로그인→Tailscale→SSH→예약/관리자/승인 수신 복구 확인.
- [ ] 퇴사 세션 종료→명시 이관→새 접근 거절→대표만 보관 폴더 접근 확인.
- [ ] AGY 검수 후 Jake의 배포·학생 안내 승인 기록. 이 문서는 발행/기기 적용 승인이 아님.
