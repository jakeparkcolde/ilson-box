# 2026-10-13 초기 업데이트 충돌 수정

- 사용자 오류: cli/template/lib/search.sh 출처 불일치로 초기 설치 중단.
- 실제 SSH: jake_mini@macmini-1.tailb24b18.ts.net. .ilson-cli / ilson 사용.
- 검색 파일에는 all 기간 지원과 Bash 3.2 호환 개선이 있어 이를 새 소스에 반영.
- 기존 확장 관리자/SNS는 공개 HEAD보다 앞선 별도 구현. snapshot.sh, web-admin-server.py, web-admin.py, web/index.html의 검토한 정확한 해시만 preserve_sha256으로 보존. 다른 해시는 계속 전체 중단. 임의 승인/강제 덮어쓰기 없음.
- 확장 관리자 보존 항목은 새 버전 코드 소유 장부에 등록하지 않음. 향후 통합 릴리스는 확장 소스와 의존성 전체를 검토해야 하며, 공개 main이 항상 최신이라는 가정 금지.
- 배포 서버 /Users/koldeumaegmini/agents/webapp/ilson/downloads/box: 2026.10.13.4 불변 ZIP/manifest/updater와 latest.json 및 bootstrap 갱신.
- 실기기 사전 check 후 적용 성공: 38개 코드 변경. 운영 폴더에서 관리대상/.git/.updates/__pycache__를 제외한 일반 파일 261개 SHA256 전후 동일. 심볼릭 링크는 내용 검사 제외.
- 실행 중인 서비스/예약 업무 재시작 없음. UI 실사용/실제 LLM 검색 호출 미실행.
- python3 -m unittest discover -s tests: 150개 통과 (36.454초), /tmp/ilson-update-tests-4.txt.
- 작업 브랜치 feat/safe-box-update-20261013, 기준 fe36313. 미커밋 상태 유지. 기존 다른 워크트리 변경하지 않음.
- 다음: 확장 관리자와 현재 통합 리서치 경로를 정식 배포 소스로 합치는 별도 검토 필요. 현재 ilson research는 팩 0.14.0 독립 실행 경로.
