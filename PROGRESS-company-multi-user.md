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

## 단계 2 — 진행 중
- 회사 소비자 연결: 큐레이터, 비공개 company 전용 Git, 보고서, 관리 영역 승인/서류함, 대표 전용 서비스 가드.
- 회사 모드 학습은 대표 runtime/state/company-learning에 별도 보관, 공용 주간 집계에서 제외.
- 2기 파일 접근 범위에서는 회사 briefing/weekly는 로컬 정형 보고, tidy는 동의된 큐레이터. 대표 UID 모델에 범용 파일 도구를 주지 않으며 사용자 지정 예약은 안전한 어댑터 검토 전 거절. 단일 사용자 자동화는 종전 경로 유지.
- 전체 회귀: hc company-tests(t36c) 실행 중, .scratch/company-full-suite.log. 실행 시작 뒤 발견한 단독 curator fixture의 모듈 의존/기존 watchdog fixture 누락은 조건부 로딩으로 수정 중.

### 2026-11-14 단계 2 결과 및 총괄 추가 결정
- 총괄 요청에 따라 대표 AI 예약을 유지. Claude 2.1.325의 로컬 `--help`에서 restricted/safe-mode 경계를 확인했다. 회사·관리 .md의 검증된 복사본만 private temp에 두고 Read/Glob/Grep만 제공. people 입력 0, Bash/MCP/쓰기 도구 0, 결과 management/reports, 알림 고정 문장. 구형 옵션 미지원은 거절. `company publish`만 명시 공용 복사.
- 기존 실행의 넓은 Read/Glob/Grep와 Bash 허용은 `job-settings.json`, 실제 호출은 `run-job.sh`에 있다. 원래 프로필만으로 회사 경계를 보증하지 않고 회사 전용 어댑터로 분리했다. 실제 유료 모델·OS 두 UID 검증은 아직 하지 않았다.
- 새 정책/파생물/AI 격리 테스트 15개 통과.
- 첫 전체 회귀: 952개, failures=8/errors=23/skipped=40, 364.524초. 당시 코드의 ①Box.company 메서드 속성 충돌 ②회사 미설정 fixture에 새 모듈을 무조건 호출 ③미재생성 course payload가 원인. 모두 수정했고 재검증 중. 이 실패 결과를 완료 판정으로 쓰지 않는다.
- t36c company-tests 결과 수집 후 terminal 제거 완료. 기존/타 세션 서비스 유지.

## 단계 3 — 운영 안내와 경계 검증 보강
- README·course/company-mac.md: 대표/직원 설치, 명시 이관 목록, 사람별 SSH/Claude, Remote Login 허용 사용자, 회사 tailnet, GUI/TCC/Keychain, 재부팅·퇴사 현장 리허설 추가.
- 퇴사 계획은 회사 루트에 해당 사용자 deny ACL을 먼저 추가해 기존 그룹 멤버십 캐시를 통한 새 경로 접근도 차단한다. 열린 핸들/이미 복사한 데이터의 회수는 보장하지 않으며 세션 종료는 현장 점검 항목이다.
- 대표 승인 actor를 실제 EUID에서 얻은 person ID로 기록. 회사 예약 pause/timeout에서 소유 CLI 프로세스 그룹과 파이프를 정리하도록 연결.
- 새 경계 테스트 총 21개 통과: 직원 가입 외부 명령 0회/재실행/기존 wrapper 보존, report 후보·서류함 hardlink, 철회된 actor 재검사, 타 UID 진단 읽기 거절, 모델 timeout 종료 포함.
- 관리자 41개·주간 요약 8개 단독 재검증 통과. 전체 재회귀 t36g 진행 중(이후 추가한 승인 actor/프로세스 정리와 테스트는 최종 전체를 다시 실행해 확인 예정).
