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
