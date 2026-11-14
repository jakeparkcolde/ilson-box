# 회사 Box 다인 사용 구현

2026-11-14 · 기준 e67f806 · feat/company-multi-user-20261114

- 승인: Codex 단독 구현, AGY는 총괄이 나중 실행. 구현 방식 재질문 없음.
- 범위: 대표 런타임 하나, 사람별 UID·Claude, company / people / management 파일 경계.
- 금지: 이 Studio의 실제 사용자·그룹·ACL 변경, chmod/rm/sudo/chown 실행, .env 열람, Mac mini 접근, push/Release.
- D-a~e 기본값은 브리프대로 적용. 실제 두 계정 ACL·GUI·재부팅 시험은 승인된 시험 Mac에서 후속 수행.
- 진행: 소스/브리프 검토 완료. 정책·파일 I/O, 회사 CLI/ACL 계획, 소비자 연결, 문서/회귀 시험 순서로 진행.
- 작업용 서버·브라우저·외부 워커 없음. 미디어 없음.

## 단계 1 — 정책·프로비저닝 계획
- `access_policy.py`: EUID→불변 ID/역할, 미등록·철회 거절, FD 기반 링크/하드링크 방어, 회사/개인/관리 범위.
- `company.py`: init 계획/명시 적용(macOS 관리자 프롬프트), 직원 join(개인 workspace/CLI), 명시 offboard 계획.
- 검증: 새 정책 테스트 9개 통과. 실제 ACL·사용자·그룹 적용 0회. 소비자 연결과 전체 회귀는 아직 진행 전.
