# 관리자 화면 수정·검증 기록 — 2026-11-06

- 기준: 총괄이 전달한 macmini-1 점검 보고 F절과 `box-admin-check-20261106/` 캡처. 대상은 Studio 작업트리 `feat/license-20261106`; macmini-1에는 접속하지 않는다.
- 4개 수정: 미완료 설치의 시작 화면과 통합 내비게이션, 미등록 예약의 경고색, 없는 팩 다운로드 안내·404, 모바일 SNS 계정 빈 공간. 라이선스 잠금 화면을 보존한다.
- 로컬 QA 서버: PID 49410, 포트 54675, 작업 전용 합성 HOME `/var/folders/fj/dg8_lcwj31z46p9hj060t2zc0000gp/T/ilson-admin-qa-apwjqt30/home`, 실행 `python3 /tmp/ilson-admin-qa-server.py`. 실제 계정·운영 데이터와 무관한 모의 상태이며 라이선스 상태를 시험 목적으로 주입한다. 작업 완료 시 이 서버와 작업 전용 브라우저 공간을 종료한다.
- 작업 전용 Ego Lite 공간 ID `49`, 페이지 `p1`. 완료 시 `finish({keep: []})`로 닫는다.
- 첫 QA 서버 PID 49410·54675는 17:54경 종료했다. 시스템 현황을 실제 기기 대신 합성 값으로 만들기 위해 새 서버 PID 53465·포트 55081, HOME `/var/folders/fj/dg8_lcwj31z46p9hj060t2zc0000gp/T/ilson-admin-qa-xteyukll/home`을 시작했다. 동일 재시작 명령을 사용한다.
- 수정 전 캡처 후 PID 53465·55081 종료. 수정 반영 서버 PID 63052·포트 56095, 합성 HOME `/var/folders/fj/dg8_lcwj31z46p9hj060t2zc0000gp/T/ilson-admin-qa-hsv8fm3z/home`으로 재시작했다.

## 화면 비교

모두 같은 Studio 합성 HOME에서 촬영한 1440×1000 / 390×844 캡처다. 실제 macmini-1 계정·업무는 읽지 않았다. 수정 전은 `before-`, 수정 후는 `after-`이며 각각 링크를 누르면 원본 크기로 볼 수 있다.

| 화면 | 1440 전 | 1440 후 | 390 전 | 390 후 |
|---|---|---|---|---|
| 첫 화면 | [전](admin-qa/before-desktop-home.png) | [후](admin-qa/after-desktop-home.png) | [전](admin-qa/before-mobile-home.png) | [후](admin-qa/after-mobile-home.png) |
| 자동화 현황 | [전](admin-qa/before-desktop-dashboard.png) | [후](admin-qa/after-desktop-dashboard.png) | [전](admin-qa/before-mobile-dashboard.png) | [후](admin-qa/after-mobile-dashboard.png) |
| 팩 보관함 | [전](admin-qa/before-desktop-packs.png) | [후](admin-qa/after-desktop-packs.png) | [전](admin-qa/before-mobile-packs.png) | [후](admin-qa/after-mobile-packs.png) |
| SNS 계정 관리 | [전](admin-qa/before-desktop-accounts.png) | [후](admin-qa/after-desktop-accounts.png) | [전](admin-qa/before-mobile-accounts.png) | [후](admin-qa/after-mobile-accounts.png) |

- 미완료 상태의 기본 진입은 홈·설정 안내이며, 홈의 설정 버튼을 누르면 같은 내비게이션에서 설정이 선택된다. 설정 완료 상태의 기본 진입은 기존 SNS 운영이며 명시적 SNS URL도 유지된다. 미확인 또는 조회 실패는 홈으로 보낸다.
- 기존 기기 관리의 홈·업무·보고서·설정을 현재 관리자 메뉴에 통합했다. 기기 관리 별도 메뉴는 없고 학습 콘텐츠에 있던 경로 안내도 새 메뉴에 맞췄다. 기존 기기 관리 링크는 홈으로 연결한다.
- 미등록 업무는 `예약 미등록`·경고색 `rgb(217, 161, 58)`으로 나타났다. 390px의 SNS 계정 영역은 최소 높이 `0px`, 실제 높이 187px로 측정됐고 가로 넘침은 없었다.
- 팩 보관함에서 없는 ZIP 이름으로 나간 요청 0건, 400 이상 응답 0건, 브라우저 콘솔 오류 0건을 확인했다. 시장조사 팩 상세의 다운로드 버튼·설명은 숨김 상태다. ZIP을 향후 배포할 때는 제공 경로를 별도로 구현해야 한다.
- 무시리얼 모의 상태에서는 `일손 라이선스가 필요합니다` 안내만 보이고 관리자 메뉴는 보이지 않았다. 시리얼 보유를 모의한 상태에서만 위 메뉴를 확인했다. 실제 사용자 기기·계정, 실제 서명 시리얼과 배포 환경에서는 시험하지 않았다.

## 시험과 배포 준비

- 신규 테스트: 준비 상태·실패 시 기본 경로, 명시적 탭 보존, 단일 메뉴와 설정 이동, 미등록 경고 배지, 누락 팩 안내/요청, 모바일 높이, 동일 출처 프레임 보안. 기존 관리자 40개, 학습 35개, 자동화 현황 12개, 프런트엔드 4개, 현재 화면 HTTP 10개, 라이선스 화면 3개를 통과했다.
- `template/web/current/pack-library`가 바뀌었으므로 다음 라이선스 릴리스 패키지를 만들 때 `tools/refresh_pack.py`로 배포용 리서치 팩을 최신 템플릿에서 다시 구성하고 `tools/build_release.py`의 동등성 검사를 통과해야 한다. 외부 배포와 Latest 승격은 하지 않았다.
- 추가 검증: 작업 전용 합성 서버에서 통합 메뉴의 `접속 종료`를 눌러 실제 세션이 종료되는지와 재접속을 확인했다. 통합 릴리스 시험 19개, 팩 갱신 시험 11개, 현재 UI 시험 13개, 공개 검사 시험 41개도 통과했다. 팩 갱신 시험은 합성 입력의 `serve.py` 허용 목록을 읽지 못했다는 기존 경고를 출력했으며 시험 자체는 성공했다.
- Close-out: Ego Lite 공간 49는 `finish({keep: []})`로 종료했다. QA 서버 PID 63052는 시작 시각·명령·cwd·포트 확인 후 SIGTERM했고 프로세스 종료 및 포트 56095 해제를 확인했다. 최초 서버 49410/54675와 중간 서버 53465/55081도 종료했다. 재시작 명령 `python3 /tmp/ilson-admin-qa-server.py` (새 임시 HOME·포트를 생성). 실제 운영 서비스와 일반 브라우저는 건드리지 않았다. 미디어 완성물이 없어 My Book 이관 대상 없음.
