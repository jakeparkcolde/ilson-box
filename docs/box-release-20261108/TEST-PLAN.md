# 통합 시험 실행 틀 (2026-11-08)

아직 1·6은 PASS가 아니다. 이 문서는 시험 준비이며 통합 성공 증거가 아니다. PASS 커밋을 총괄에게 받은 뒤에만 병합하고 실제 코드 인터페이스를 다시 확인한다.

## 6.4 → 새 버전

- 원본은 작업폴더 바깥 `~/orca/workspaces/ilson-box/box-release-20261108-scratch/6.4/`에 보존한다. 먼저 `python3 docs/box-release-20261108/preflight_64.py --baseline "$BASELINE" --candidate-manifest "$NEW_MANIFEST" --candidate-archive "$NEW_ZIP"`를 실행한다. 이 검사는 양 ZIP·manifest의 해시와 멤버, 구 updater의 `allowed()`만 확인한다. 실제 업그레이드 대체 불가.
- 완전히 새 임시 HOME과 분리된 CLI·Box 경로를 준비한다. 6.4 ZIP은 업데이트 묶음(`cli/`, `box/`)이므로 설치기 자체가 아니다. `2e6fd52`의 설치기 및 ZIP의 `cli/`를 로컬 소스로 사용하여 실제 설치 경로와 샌드박스 초기화가 가능한지 먼저 확인한다. 실제 launchd·계정·시스템 변경이나 외부 접속을 막고 실행 경로와 제한을 기록한다. 설치기가 내부적으로 사용하는 권한 변경·임시 파일 정리도 지시의 금지 범위와 충돌하는지 총괄에 확인할 것. 단순 ZIP 추출은 실제 설치로 보고하지 않는다.
- 가짜 볼트 노트, 설정, 학습 자료, 텔레그램 설정을 만들고 내용을 해시로 보관한다. 실제 토큰과 사용자 자료를 사용하지 않는다. 신규 ZIP/manifest의 전체 멤버를 확인하고 구 6.4 설치본의 `tools/update.py --home <임시 Box> --cli <임시 CLI> --manifest <새 manifest> --archive <새 ZIP>`를 구 프로세스로 실행한다. 외부 패키지 설치와 실제 서비스 실행은 격리해야 하며, `ensure_runtime`을 대체하면 그 사실과 보장 범위를 기록한다.
- 모든 산출물의 해시, 보존 자료 해시, 구 updater 자신의 교체 및 다음 실행 상태를 확인한다. `preserve_sha256`가 있는 경우 보존된 파일과 사유도 별도 확인한다. 받은 파일 첫 사용 시 폴더 생성 및 미동의 수신기의 launchd 미등록을 독립 확인한다. 둘 다 4·1 PASS 전에는 해당 없음/미실행으로 기록한다.
- 버전·정식 research pack·이전 배포 manifest는 최종 병합 및 총괄 신호에 따라 정한다. 빌드는 `tools/build_release.py --preserve-from <6.4 manifest>`를 사용하고, 새 커밋 기준 `tools/check_public.py --exact-commit`과 실제 `publish_release.py`의 비공개 드라이런 경로를 확인한다. 보존 목록을 무시하거나 가드를 끄지 않는다.

## 1+6 합성 서버 통합

`fake_services.py`의 `fake_services()`는 루프백 전용 Naver/Telegram 서버와 요청 기록을 제공한다. 각 시험마다 새 서버·임시 Box를 쓰고 Naver transport를 루프백으로 명시적으로 연결한다(그 외 주소 차단). Telegram은 합성 토큰과 endpoint를 사용한다. 승인 저장소와 어댑터는 진짜 병합된 구현을 사용한다. 현재 fixture는 인터페이스 준비이고 통합 테스트가 아니다.

1. `approval_actions.load_all()`이 실제 `replies_dispatch.register()`를 호출하고 액션을 등록하는지 검증. 실제 문의 수집→초안→승인 요청→Telegram 카드→합성 버튼 수신→실제 dispatch 경로 실행. 카드에 합성 원문이 없고 답변 및 로컬 확인 문구가 있는지, 승인 전 PUT 0회·승인 뒤 verify GET 이후 PUT 정확히 1회·재클릭에도 1회인지 검증한다.
2. 원격의 이미 답변된 문의와 변경된 문의 각각 `changed`, PUT 0회. PUT 연결 끊김/타임아웃 또는 5xx는 `result_unknown`, 재시작과 재승인 시도에도 자동 재전송 0회. fixture의 `disconnect`는 연결 끊김이지 타임아웃 자체는 아니므로 별도로 timeout을 주입한다.
3. 로컬 관리자 인증 화면에서 `local_context`의 합성 원문이 텍스트로 표시되고 HTML 실행이 불가능함을 WebKit에서 확인. Telegram 카드와 저장되는 meta/리포트에 원문이 없는지도 검증한다.
4. 실제 승인 저장소의 기간별 상태 건수를 만들고 3번 리포트가 실제 `weekly_counts` 결과를 읽는지 검증한다. 빈 DB와 경계 시각도 확인한다.
5. 진짜 HTTP 요청과 DB 상태·호출 순서로 판정한다. 1·6 개별 단위 시험의 가짜 store 결과를 통합 결과로 대체하지 않는다.
