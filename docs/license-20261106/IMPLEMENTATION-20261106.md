# 라이선스 2단계 구현·검증 기록 — 2026-11-06

## 범위와 현황

- 확정 설계 커밋 `e6fedb4`, 구현은 이 기록과 같은 후속 커밋. 시작점 6.2 `a90fa0b`. 공개 저장소 소프트 잠금, 무시리얼 설치와 6.2 키트 유지, 설치 요약, 서명 활성화, 오프라인 유예, CLI/웹/예약 잠금, 스냅샷 및 로그 보호를 구현했다.
- 서버: `server/license/api/v1/[action].js`, Supabase migration `server/license/migrations/001_license.sql`, 발급/관리 `server/license/issuer.py`, 배포 사전 확인 및 스테이징 스크립트·운영 설명 `server/license/README.md`. 클라이언트는 `template/lib/license.py`다.
- 운영 공개키와 API 주소는 의도적으로 비어 있다. 실운영 키를 만들거나 사용하지 않았다. `python3 server/license/preflight.py`는 두 설정이 없다고 실패하는 것이 현재 정상이다. 이 상태의 Box는 실사용 시리얼을 검증할 수 없고 배포 준비 완료가 아니다.
- 사용자 자료 보존과 소프트 잠금이 목표다. 코드 수정·오래된 버전 실행·기존 키트 파일 직접 열기를 막을 수 없고, 서버에서 취소되었어도 오프라인 기기는 마지막 승인부터 최대 14일 이용할 수 있다. Pure Python Ed25519는 외부 보안 감사를 받지 않았으며 상수 시간 구현이 아니다.

## 시험 결과

- 전체 기존·신규 회귀: 38개 모듈 모두 통과 (`/tmp/ilson-license-full-suite-2.log`). 이후 설치 요약 변경에 대해서는 `test_setup.py` 58개와 `test_course_kit.py` 6개를 다시 통과했다. 기존 웹·예약 등 비라이선스 기능 시험은 라이선스 허용을 명시적으로 모의하고, 실제 서명/무시리얼 경계는 별도 시험으로 다룬다. 테스트 전용 Pillow는 `/tmp/ilson-license-test-deps`에만 설치했다.
- RFC 8032 서명 벡터 2개, 변조 거부, Python 발급과 Node 서버 서명 호환, 온라인 취소, 최초 오프라인 14일, 재입력, 시계 복구, 임시 TLS 모의 서버, 스냅샷 비밀 제외, 업데이트 허용 경로를 확인했다. 별도 `test_license_integration.py`는 임시 HOME에만 시험 키를 생성하고 삭제하며, 무시리얼 CLI/예약·watchdog과 서명된 키트 경로를 확인했다. `test_license_web.py`는 안내 화면·API 차단·백그라운드 작업 중지·마스킹을 확인했다.
- 로컬 PostgreSQL 17 임시 클러스터에서 서로 다른 세 연결의 동시 기기 등록을 실행해 2대 승인/1대 거부, anon/authenticated 권한 차단, 온라인 취소를 확인했다. 시험 종료 시 클러스터는 정상 종료하고 임시 데이터는 정리했다. 별도 PGlite 모의 DB + Node 24 API 시험은 발급 등록·기기 제한·월납 연장·취소·잘못된 관리자 비밀에 대한 속도 제한을 통과했다. Node 24와 Python 표준 라이브러리 환경에서 실제 Supabase/Vercel 연결은 시험하지 않았다.
- PostgreSQL 시험을 위해 Studio에 Homebrew `postgresql@17`을 설치했다. Homebrew가 `/opt/homebrew/var/postgresql@17` 기본 클러스터도 생성했으나 서비스를 시작하지 않았다(`pg_ctl status`: 서버 없음). 시험에서 사용한 임시 서버는 종료했다. PGlite는 `/tmp/ilson-license-pg-test`에 설치했다.

## 승인 및 다음 단계

- Jake의 2026-11-06 결정: 구현 검수 통과 뒤 총괄이 콜드바이트 팀 Vercel `ilson-license`의 기본 도메인과 Supabase `ilson-license` 서울 지역을 사용한다. 1기 4명은 각각 일시불·긴 유한 만료를 쓴다. 이 결정은 지금 이 작업자가 리소스를 만들거나 배포하라는 지시는 아니다.
- 총괄: 독립 구현·보안 검토 → 승인된 절차에서 Studio 키와 관리자 비밀 준비 → Supabase migration/RLS와 서버 환경변수 구성 → Vercel 기본 도메인 스테이징/검증 → Box 공개키·URL 고정 → Jake용 발급/확인 → 학생별 발급 → Jake 승인 후 학생 전달. 상세 순서와 명령·복구는 `server/license/README.md` 참조.
- 아직 하지 않은 일: Vercel/Supabase 생성·실제 배포, 실제 서명 키 생성·사용, 운영 URL 확정, Jake/학생 시리얼 발급, 실제 기기 활성화, 학생 발송. 사용자 지시에 따라 macmini·macmini-1에 접속하지 않았다. 푸시·릴리스도 하지 않았다.
