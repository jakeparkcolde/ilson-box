# 일손 Box 라이선스 배포·운영 절차 (준비본)

상태: 로컬 개발 및 시험 단계. 이 문서는 리소스 생성이나 배포를 실행하지 않는다. Jake 승인(2026-11-06): 검수 통과 후 총괄이 콜드바이트 팀의 Vercel `ilson-license`(기본 도메인)와 Supabase `ilson-license`(서울 지역)를 만든다. 프로젝트·DB·환경변수·도메인·키는 아직 생성하거나 변경하지 않았다. 1기 학생 4명은 각자 다른 일시불 시리얼과 Jake가 정하는 긴 유한 만료를 사용한다. 총괄은 학생 발송 전 별도 승인을 받는다.

## 배포 전 필수 검증

1. `docs/license-20261106/SPEC.md`의 독립 코드·보안 검토, 회귀 시험, 실제 PostgreSQL 독립 연결 간 동시 등록 시험과 신규 기기 오프라인 시험을 통과한다. 순수 Python Ed25519는 외부 보안 감사를 받지 않았다.
2. 실사용 서명 키의 생성·사용은 이 작업에서 금지되어 있다. 총괄이 검수 후 허가된 별도 절차에서 Studio의 `~/.config/ilson-license/`에만 0600 키를 만들고 안전한 백업을 결정한다. 개인 키는 Vercel/Supabase/저장소·로그·대화·학생 기기로 보내지 않는다. 승인된 추후 절차에서 `python3 server/license/issuer.py init-key`는 새 파일만 0600으로 만들고 공개키만 출력한다. `python3 server/license/issuer.py init-admin`은 관리자 비밀을 만들고 그 값을 출력하지 않는다. 이 두 명령은 현재 실행하지 않았다. 코드의 `PUBLIC_KEYS`에 승인된 해당 **공개키만** 넣고 키 ID를 일치시킨다. 키 설정 전에는 라이선스 활성화가 동작하지 않는다.
3. 검수 통과 후 총괄이 Supabase 서울(Seoul) 지역의 `ilson-license`를 만들고, 백업·권한·비용을 확인한다. SQL 편집기/승인된 migration 절차로 `migrations/001_license.sql`을 적용한다. anon/authenticated의 DB 접근과 RPC 차단 및 service_role만 함수 실행 가능함을 실제로 확인한다. DB 비밀은 고객 기기와 저장소에 넣지 않는다.
4. Vercel 콜드바이트 팀에 `ilson-license` 프로젝트를 만들고 프로젝트 루트를 `server/license`로 설정한다. 기본 도메인을 실제 배포에서 확인한다. 환경변수는 `SUPABASE_URL`(Config), `SUPABASE_SECRET_KEY`(Secret), `ILSON_ADMIN_SECRET`(Secret), `ILSON_PUBLIC_KEY_1`(공개키 64자리 16진수 Config; 키 ID에 맞게 변경)이다. 관리자 비밀은 Studio의 `~/.config/ilson-license/admin-secret`에 0600으로 보관하고 사용자 기기에는 넣지 않는다. Vercel 환경변수에서 발급 개인키를 설정하지 않는다. 고정 기본 도메인 주소를 미리 추측하지 않는다.
5. 서버 스테이징 전 `python3 server/license/preflight.py --server`로 공개키와 필수 파일을 확인한다. 스테이징 URL 확인 뒤 운영 기본 도메인을 확정해 Box의 `template/lib/license.py`에서 `API_URL`에 HTTPS로 명시하고, Box 릴리스 전 `python3 server/license/preflight.py`로 두 설정을 검사한다. 두 검사는 외부 요청이나 변경을 하지 않으며 정상 종료도 승인이나 보안 검토를 대신하지 않는다. Vercel은 변경한 환경변수를 새 배포부터 적용한다.
6. 검수 통과 후 총괄은 연결된 콜드바이트 프로젝트를 확인하고 `ILSON_LICENSE_REVIEW_PASSED=yes sh server/license/deploy.sh`로 운영 빌드를 도메인 배정 없이 스테이징한다. 필요한 Vercel 프로젝트 연결·환경 준비는 사전에 승인된 절차로 진행한다. 스테이징을 검증한 뒤에만 총괄이 `vercel promote <검증한-배포-URL>`을 실행한다. 스크립트는 지금 실행하지 않았다.
7. 배포한 서버의 nonce·TLS·RLS·속도 제한·2대 한도·취소·연장·로그 가림을 검증하고 Jake용 시리얼을 발급한다. Jake가 직접 지정 기기에서 온라인·오프라인 활성화를 확인한다. 이 작업자는 macmini와 macmini-1에 접속하지 않는다. 실제 배포/릴리스 및 발송은 총괄이 맡는다.

## 로컬 시험

- 저장소 루트에서 `python3 -m unittest discover -s tests -p 'test_license*.py' -v`를 실행한다. `test_license_postgres.py`는 `/opt/homebrew/opt/postgresql@17/bin`의 PostgreSQL을 사용해 임시 클러스터를 열고 종료한다. 설치되지 않으면 해당 시험은 건너뛴다.
- 서버 디렉터리에서 `npm ci` 후 `npm test`로 PGlite 모의 DB와 API 시험을 실행한다. Node 24를 사용한다. PostgreSQL 실제 독립 연결 경합 시험을 PGlite 시험으로 대체하지 않는다.
- 시험 인증서·서명 키는 격리된 임시 폴더에서만 생성하며 실제 사용자·운영 키와 무관하다.

### 스킬 나눔 (미배포)

검수와 별도 운영 승인 후 `migrations/002_skill_share.sql`을 적용하고 서버를 배포한다. `ILSON_SKILL_COHORT_ONLY=true`일 때만 같은 기수의 승인 항목을 표시하며, 기본값은 유효한 모든 기수에 공개다. 공개 대상에는 발급 기록의 이름 대신 무작위 별칭을 표시한다. 강사는 자신의 Studio에서 `python3 server/license/skill_admin.py`를 실행해 관리자 비밀을 숨김 입력하고 안내된 로컬 주소에서 대기 내용을 검토한다. 비밀은 저장하지 않으며 종료는 Ctrl-C다. 화면은 25건씩 페이지를 넘겨 표시한다. 개인정보 자동 검사는 완전하지 않으므로 업로더와 강사가 실제 내용을 확인해야 한다. 기존 6.4 배포물에는 이 기능이 없으며 새 릴리스 준비 및 검증이 필요하다.

## 발급 예시 (명령 형식만, 실행하지 않음)

`--key`는 이미 Jake가 Studio에서 안전하게 준비한 32바이트 시드의 16진 문자열이 든 0600 파일이다. 출력은 0600 시리얼 파일이며 표준 출력에 시리얼을 인쇄하지 않는다. 아래 날짜와 표시 이름은 예시다. 실제 긴 만료일·대상과 승인된 서버 URL을 총괄이 확정한다. 민감한 값을 터미널 기록이나 대화에 붙이지 않는다.

```sh
python3 server/license/issuer.py issue --key "$HOME/.config/ilson-license/signing-key" \
  --output "$HOME/.config/ilson-license/student-01.serial" --kid 1 --cohort 1 \
  --plan one-time --issued 2026-11-06T00:00:00Z --expires 2036-11-06T00:00:00Z
python3 server/license/issuer.py register --server 'https://승인된-기본도메인' \
  --serial-file "$HOME/.config/ilson-license/student-01.serial" --display-name '1기-01'
```

Jake용을 먼저 발급·등록하고, 학생 4명의 파일을 각기 따로 발급·등록한다. 파일명을 바꾸더라도 같은 시리얼을 재사용하지 않는다. 관리 CLI의 `revoke`, `devices`, `release-device`는 같은 `--server`와 `--serial-file`을 쓰고, `release-device`는 `--target-device`에 `devices`가 표시한 기기 해시를 지정한다. 월납 고객의 `renew-payment --paid-until 2027-01-01T00:00:00Z`는 DB 날짜만 바꾼다. 동일 요청을 재시도할 때는 첫 성공 메시지에 표시되는 `--request-id`를 사용한다. 통신이 응답 전에 끊긴 경우를 위해 운영 시 호출자가 요청 ID를 미리 생성·기록해 전달한다. 12개월 서명 만료 이후에는 새 시리얼이 필요하다.

## 장애와 복구

- 서버가 닿지 않아도 서명 유효 시 최초 또는 마지막 승인부터 최대 14일(서명 만료가 더 빠르면 그때까지) 사용한다. 온라인 취소 확인은 즉시 차단한다. 인터넷 없는 기기의 취소는 즉시 전파되지 않는다.
- 관리자 비밀을 분실·유출하면 Jake 승인 후 Vercel Secret과 Studio 0600 보관본을 교체하고 새 배포를 검증한다. 서명 키 유출/분실은 별도 사고로 대응한다. 백업이 없으면 동일 키 복구를 약속하지 않는다.
- `ilson license status`, `ilson license activate`, `ilson license deactivate`와 설치/도움말은 잠겨도 쓸 수 있다. 기기 해제는 서버 연결이 필요하다. 잘못된 시리얼이 기존 정상 상태를 덮지 않는다.
- 시리얼을 실행 인자로 주면 셸 이력·프로세스 목록에 남을 수 있으므로 `ilson license activate` 후 숨김 입력 또는 `--stdin`을 쓴다. 설치 중 키트는 6.2처럼 파일로 생성된다. 공개 저장소와 사용자 파일은 완벽하게 잠글 수 없다.

### 롤백

- Box 업데이트 문제는 해당 기기에서 `ilson update --rollback`으로 직전 코드로 복구한다. 볼트·라이선스 상태를 보존하며 실행 중인 업무를 강제 종료하지 않는다. 복구 가능 여부와 정상 동작은 해당 기기에서 확인한다. 이전 코드에는 라이선스 잠금이 없을 수 있다.
- 서버 장애 시 Vercel에서 현재 프로젝트와 팀의 이전 정상 배포 ID/URL을 `vercel ls --scope <팀>`과 `vercel inspect <배포>`로 확인한 뒤, 승인된 운영 담당자가 `vercel rollback <이전-배포-ID-또는-URL> --scope <팀>`을 실행한다. 라우팅 변경 후 스모크 시험과 현재 URL을 확인한다. 서버 롤백은 DB 스키마나 환경변수를 자동으로 되돌리지 않으므로 호환성을 먼저 확인한다. 장애 중 서버에 닿지 않는 기기는 기존 오프라인 유예 정책을 따른다.
