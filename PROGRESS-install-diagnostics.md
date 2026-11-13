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
