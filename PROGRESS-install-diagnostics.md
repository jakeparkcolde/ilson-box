# 설치 진단 구현 진행 · 2026-11-13

- 목표: IMPL-BRIEF-1, DESIGN 단계 1–4 + 강의판 갱신 경로. 기준 49f683a.
- 승인: 지정 worktree/branch 유일 writer. 로컬 구현·시험·커밋·AGY 묶음 작성. push/Release/외부 전송/실기기 설치/AGY 실행 금지. 보고 hc send t2v5.
- 환경: Mac Studio Mac17,14. 브랜치 feat/install-diagnostics-20261113, 시작 clean.
- 단계 1 진행: 엄격한 이벤트 허용 목록·TSV/JSONL 독자·요약·로컬 공유·보존·안전 doctor 작성.
- 검증: 아직 실행 전.
- 실행 프로세스: 없음. scratch: .scratch/install-diagnostics (삭제하지 않음).
- 단계 1 커밋: 5c83b97. 계약 시험 5건 통과.
- 단계 2: POSIX TSV 기록기, PowerShell JSONL 기록기(no-BOM UTF8Encoding(false)), 독립 doctor 및 내장 생성기. 신규 시험 합계 8건 통과 (DNS/HTTP 503/timeout·첫 fetch 실패·원문 비영속·Python 없는 doctor·dry-run 0 writes·중단 판정 포함). shell syntax 통과.
- Windows 한계: 현재 pwsh 없음. 실제 5.1 시험 미실행; 정적 검수 및 추후 승인된 Windows sandbox 검수가 필요.
- 단계 3 연결: 세 설치기 첫 실행 구간에 같은 native 소스 내장, setup run 연결, required 실패/의존 생략, download/execute 분리, 절대 경로 버전 후조건, PATH 보존. full CLI --version / doctor 안전 분기 및 강의 doctor를 license 이전에 분기.
- 단계 7 일부: 파일별 known hash map, 전체 사전 검사, 백업 manifest, 쓰기 실패 자동 복구, 명시 rollback, 알려진 Intel wrapper/Python 선택 갱신. payload 재생성.
- 검증: setup 58건 PASS (.scratch/install-diagnostics/setup-final.log), course installers 24건 PASS/4 skip, course learn 7건 PASS, upgrade/rollback 4건 PASS. 원래 mock은 실행 존재만 가정했으므로 버전 probe mock/fixture를 추가. K/base64 순서 fixture는 새 비교 문구에 맞춰 갱신.
- 테스트 실행 메모: hc TTY를 물려준 첫 setup 시험은 기존 텔레그램 대화 입력 대기로 2건 timeout. stdin /dev/null로 재실행해 통과. native retention 초기 bash3.2 case 파서 오류는 if문으로 고치고 shell syntax 및 재시험 통과.
- 현재 추가 작업: immutable inline bootstrap·shell 확인·보존 통합 시험, Windows 정적 제약·안전성 보강, 문서 및 AGY 묶음. 전체 suite t33b 실행 중 (로그 .scratch/install-diagnostics/full-suite.log).
- 단계 4: immutable SHA URL+SHA256 inline bootstrap/생성기, 독립 doctor 한 줄·오프라인 파일 경로, current/new 확인 및 명시 opt-in shell simulation, 명령 충돌·판본·폴더·smart dash 안내. 네트워크 전송 없음. 정확한 사용자 경로 인용, 출력 크기/5초 제한. native/PS 보존·환경/PATH boolean·지원 파일 정제 보강.
- 신규 진단 통합17건 PASS (.scratch/install-diagnostics/diagnostics17.log): 실제 setup_tools Claude DNS / Codex503 / execute 의존 생략 / PATH 미확인 분리, Python3.9 Intel, inline 첫 fetch 실패 및 hash 불일치 부분 실행 0, shell current/new/simulation/충돌, 링크 거절·잘못된 설치기, retention20건, 로컬/공유 정보 가림, payload parity/PS5.1 정적 제약.
- 첫 전체 suite: 878건 / 38 skip / 16 failure. 15개는 update_feed CLI mock이 새 버전을 출력하지 않아 생긴 실패 → version fixture 보완. 1개는 scratch 실패 로그가 개인정보 repository scan 대상 → scratch gitignore 추가. 해당 update_feed18건 재시험 PASS (.scratch/install-diagnostics/update-feed.log). 기존 검사 기준은 완화하지 않음.
- 문서: docs/install-diagnostics.md, README, docs/설치, 강의 시작 안내. 공개 배포 승인 전임을 명시. 강의 kit 내장 guide/payload 재생성.
- 최종 보완: full-mac OS/Rosetta 오선택을 exit2로 기록, setup preflight/web/auth 구간, Mac shell 확인을 기존 TSV에 append하여 Python 없는 doctor에서도 읽음, 원래 known wrapper의 Windows 줄바꿈 차이만 안전 갱신, 문서/내장 바이트 일치.
- 영향 재검증: 진단17건, setup58건, course 패턴 전체 통과(Windows 등7 skip). .scratch/install-diagnostics/affected-*.log.
- 두 번째 전체 suite: 882건 /38 skip /1 error. 출력 상한 검사 중 host가 process-group 신호를 EPERM으로 거절한 경우가 발견됨. 소유 Popen 프로세스만 종료하는 fallback을 추가하고 이 거절 경로를 합성 시험에 포함. 이 수정 뒤 최종 전체 재검증 예정.

## 최종 검증 · 2026-11-14 KST

- 제품 소스: 0cf2716. 최종 전체 회귀 `python3 -m unittest discover -s tests -v < /dev/null`: **882 tests, OK (skipped=38), 실패/오류 0**, 343.882초. 로그 `.scratch/install-diagnostics/final-regression.log`.
- 전체 회귀 collection 이후 추가한 Intel wrapper 시험 1건(known Python 경로 갱신/백업 + 사용자 편집 보존)까지 포함하여 course upgrade **5건 별도 PASS** (`upgrade-wrapper-final.log`). 제품 코드는 이후 바꾸지 않았음. 현재 전체 수집 시 총883건이며, 전체882+추가1건을 검증한 상태임.
- 신규 검증: install diagnostics17 + course upgrade5. 기존 setup58, course44/7skip, update_feed18 영향 시험 PASS. 실제 PowerShell5.1/PS7·Windows 실기기 검증은 미실행(pwsh 없음); 배포 전 별도 필요.
- `git diff --check`, shell syntax, Python compile, native/source 및 course 내장 payload byte parity 통과. push/Release/GitHub/외부 진단 전송/실학생 설치/AGY 실행 없음.
- AGY 자료: Studio_base 해당 handoff 폴더의 `agy-impl1-review/BRIEF.md`, `target.diff`, `install-commands.json` (현재 로컬 SHA의 검토 후보이며 공개되지 않은 URL은 실행하지 않음). 총괄 t2v5가 검토를 시작하고 병합함.
- Close-out 2026-11-14: 매체 산출물 없음(archive 대상0). 소유한 종료된 시험 터미널 t332/t334/t338/t339/t33b/t33c/t33d/t33f 8개를 상태·PID·argv 확인 후 hc rm. 별도 브라우저/미리보기/공유 서버 기동 없음. 실행 중 작업 없음. `.scratch/install-diagnostics/` 로그·시험 자료는 검토를 위해 보존(필요 시 이 폴더만 정리 대상). 현재 구현 worker/총괄과 무관한 서비스는 유지.
