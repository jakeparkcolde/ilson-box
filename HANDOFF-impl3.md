# IMPL-3 작업 인계 · 2026-11-14

작업은 계속 진행 중. 컨텍스트 수치가 노출되지 않아 비율은 추정하지 않았다. 구현 결정과 긴 회귀 출력을 보존하기 위한 중간 기록이다.

## 목표·승인
- IMPL-BRIEF-3-MULTI.md 구현. 이 worktree만 단독 writer. 기준 e67f806, branch feat/company-multi-user-20261114.
- Codex 구현, AGY는 총괄 t2v5가 나중 실행. `hc send t2v5` 한국어 보고 승인.
- 실제 이 Mac 사용자/그룹/ACL 변경, chmod/rm/sudo/chown 직접 실행, .env, Mac mini, push/Release 금지. 테스트 임시 fixture만 사용.
- t2v5 추가 지시: 대표 AI 예약을 유지할 수 있는 강제 경계가 있으면 company+management 입력, people 제외, management/reports 기본 출력, 명시 공개만 company.

## 현재
- 커밋 338ec29: access_policy.py, company.py, 정책 테스트 9개, 진행 기록.
- 미커밋: 모든 소비자 연결, company_runtime.py/company-client.sh, 15개로 늘린 테스트, curator course 동기화+payload 재생성. `git status` 확인할 것.
- 정책: root 소유 중앙 config, UID→ID/역할, 기본 거절, FD 기반 I/O, symlink/hardlink 거절. 회사 원본 루트 /Users/Shared/Ilson/<id>/vault. 대표 runtime은 기존 private home 유지.
- init는 명령 계획 출력, --apply+TTY yes+osascript 관리자 인증. 실제 실행 0. 직원 join은 표준 계정 로컬 CLI/workspace만, own Claude, 추가 runtime 없음. offboard는 대표 명시 계획/적용만. publish는 대표 관리 보고를 새 company 파일로 명시 복사.
- 회사 curator: owner company-only→company/journal/curator, staff company+본인→people/self/journal/curator. 개인 자동 예약 없음. 직원 license 비밀 안 읽음.
- snapshot: 대표 runtime/state/company-history/repository에 company-only Git. 기존 전체 이력은 원래 private 위치 보존.
- 승인/서류함: management, Telegram 승인 본문 전송 차단. selflearn은 runtime/state/company-learning private.
- 대표 웹은 기존 token/대표 UID만. 보고 후보는 company/reports+management/reports (대표 전용 응답), 개인 후보는 없음. 최근 수정: 기존 Box.company() 메서드와 새 속성이 충돌하여 새 속성을 company_policy로 수정.
- 대표 AI: 설치된 Claude 2.1.325 --help 읽기 확인. --restricted는 cwd 파일 도구 제한, --safe-mode는 CLAUDE.md 등 자동 주입 중지(OAuth 유지). 허용 .md만 2 MiB 이내 private temp 복사, Read/Glob/Grep만, Bash/쓰기/MCP/add-dir 없음. 출력은 helper가 management/reports에 새 파일, Telegram 고정 문장. 옵션 없는 CLI는 거절. 실제 AI 호출은 하지 않음. fake CLI 인자/입력 격리 테스트만 통과.

## 검증·실패·프로세스
- `python3 -B -m unittest discover -s tests -p test_company_access.py -v </dev/null`: 15개 통과.
- curator 단독 초기 실행: standalone import dependency 23 error→회사 마커 있을 때만 import로 수정. watchdog fixture에 access_policy 누락 1 failure→common.sh 회사 마커 조건부로 수정.
- 전체 suite는 `hc company-tests` 주소 t36c, pid 62631, 부모 t366로 실행 중. 로그 `.scratch/company-full-suite.log`. 시작 뒤 코드 변경이 있어 최초 결과는 최종 판정 아님. 결과 수집하고 hc rm company-tests로 소유 terminal만 정리. 이후 수정본 전체 다시 실행 필요.
- course payload parity 실패가 실행 중 보였음→course/install_payload.py 구 curator hash 추가+`python3 course/pack_course.py` 재생성 완료, 재검증 필요.
- source code 실제 import/syntax/단독 이전 suite/full suite 최종 확인, 설치 계획 mock 테스트 확대, 공개 검사, 문서/AGY bundle 아직 남음.
- 서버·브라우저·AGY agent 직접 시작 없음. 테스트 fixture가 임시 서버/번들 Chromium을 쓸 수 있음; suite cleanup 확인. 미디어 없음.

## 다음
1. 전체 첫 suite 결과/실패 읽고 수정. 특히 새 access_policy import가 fixture/강의 독립 실행을 깨는지, 업데이트 CLI sys import 확인.
2. 회사 코드 점검: ACL root anchor, 가입 재실행/기존 wrapper 보존, offboard 재실행·철회, 명시 이관 목록, private diagnostic, report/inbox/approval 누출 테스트.
3. README + course/company-mac.md 대표/직원/SSH/GUI/재부팅/현장 checklist/제약 작성.
4. 단계별 커밋. stdin /dev/null 전체 943 baseline+new suite green, 실제 계정/ACL/AI/재부팅 미실행 명시.
5. `agy-impl3-review/BRIEF.md` + `target.diff` e67f806..HEAD 준비(자기 diff 포함 피함). AGY 실행 안 함. 최종 t2v5 한국어 보고.

복사용 재개 프롬프트:
> 이 worktree의 HANDOFF-impl3.md와 PROGRESS-company-multi-user.md를 읽고 IMPL-3 구현을 이어가라. mode 결정됨(단독 구현/AGY 나중). t2v5 추가 AI 격리 결정을 유지하고, 실행 중 company-tests 결과를 먼저 확인하라. 실제 ACL·사용자 변경/push/Release/Mac mini/.env 금지. 최종 full suite와 agy-impl3-review 번들을 완성하여 hc send t2v5로 한국어 보고하라.
