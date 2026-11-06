# 일손 라이선스 배포 대기 기록 — 2026-11-06

## 최신 진행 상황 — 2026-11-06

아래의 Marketplace 대기와 미실행 목록은 당시 기록이다. Jake가 승인한 Supabase `ilson-license`(ref `nzhsnuwmtocstazadsho`, 서울, Pro 조직, Micro, 추가 월 $10)를 직접 만들었고 Marketplace 연결은 사용하지 않는다. Vercel 프로젝트는 아래에 기록한 기존 프로젝트를 사용한다.

- 관리자 화면 전환 재수정 `a1970bf`: WebKit 실브라우저 회귀, 웹 관리자 및 학습 안내 시험 통과. `ADMIN-WORK-20261106.md` 참조.
- Supabase 대시보드가 제공한 서울 세션 풀러로 `001_license.sql`을 적용했다. 네 테이블 RLS 활성, 두 RPC는 anon/authenticated 실행 불가 및 service_role 실행 가능함을 확인했다. DB 비밀번호는 Studio의 0600 파일에서만 읽었다.
- 새 전용 Supabase secret key `ilson_license_vercel`을 만들고 해당 키의 실제 RPC 호출을 확인했다. 디스크에 키를 저장하지 않고 권한 0600 FIFO와 메모리로 Vercel production의 Sensitive `SUPABASE_SECRET_KEY`에 설정했다. `SUPABASE_URL`은 Config, Studio에서 생성한 `ILSON_ADMIN_SECRET`은 Sensitive로 설정했다. Studio 설정 디렉터리는 소유권을 확인하고 0700으로 맞췄다.
- 보안 사고: 이 Codex/Herdr 작업 대화의 2026-11-06 `aside repl` Supabase API Keys 화면 스냅샷 출력에서 기존 `default` secret key의 일부가 표시됐다. 조각은 이 문서에 기록하지 않는다. 총괄 지시에 따라 새 전용 키의 RPC 성공을 확인한 뒤 노출된 `default` secret key를 Supabase 대시보드에서 삭제했고 성공 메시지를 확인했다. 다른 키나 publishable key는 삭제하지 않았다.
- 배포 준비 중 Supabase 공식 문서에 맞춰 서버의 두 RPC 요청에서 opaque secret key를 `apikey`에만 보내도록 수정했다. PGlite 서버 시험 2개 통과. 실제 Vercel 서버 스모크는 아직이다.
- 이후 순서: 서버 배포와 스모크 → Studio 운영 서명 키 → 공개키 Vercel 설정 및 재배포 → 공개키·실제 URL을 담은 GitHub prerelease → Jake 시리얼 1개 발급·등록 → 합성 HOME 활성화 및 status. 1기 학생 발급과 Latest 승격은 별도 지시 전 금지.

후속 확인: `https://ilson-license.vercel.app` 운영 배포에서 health 200, 잘못된 시리얼 400, 잘못된 관리자 인증 403, 유효 관리자 인증 후 잘못된 시리얼 400을 확인했다. Studio에서 서명 키를 만들고 공개키를 Vercel에 등록해 재배포했다(배포 ID `dpl_35tWjM4PEiJA99RhXFz3TwNiVi32`). 이 기록 시점에 prerelease 생성, Jake 시리얼 발급 및 합성 HOME 시험은 아직 수행 전이다. 아래의 미실행 항목과 이어하기 프롬프트는 과거 기록이다.

## 목표와 최신 지시

총괄 t3q는 Jake가 승인한 Vercel 콜드바이트 팀 `ilson-license`와 Supabase `ilson-license` 서울 지역으로 배포한 뒤, GitHub prerelease 및 Jake 시리얼 1개를 준비하도록 지시했다. 1기 학생 4명 발급과 Latest 승격은 별도 신호 전 금지. Jake 로그인이나 결제 확인이 필요하면 그 지점에서 멈추어 총괄에게 한 줄로 보고한다. 시리얼·개인키·인증정보 원문은 저장소·로그·대화에 넣지 않는다. macmini/macmini-1 접근 금지, 작업자가 직접 chmod/sudo/chown/rm 금지.

## 완료 및 검증

- 설계 `e6fedb4`, 2단계 구현 `4720cd2`, Antigravity 검수 지적(P2 2건·P3 2건) 수정 `f211882`. 수정: 모든 인자의 도움말 감지, 다른 시리얼 거절 시 기존 상태 보존과 denied 재확인, paid_until null 거절, Box/Vercel 롤백 절차. 배포 health 확인을 위한 `/api/health`도 추가했다.
- 라이선스 시험 22개, 강의 키트 6개, Node 24 서버 2개 통과. 라이선스 시험에 로컬 PostgreSQL 독립 연결 3개 동시 등록·RLS 검증 포함. 그 전 전체 회귀 38개 모듈 통과. 현재 실행 중인 테스트·태스크 서버 없음.
- Vercel CLI 로그인 계정 `jakeparkcolde`. 사용 가능한 팀은 `jakeparkcoldes-projects`이며 기존 `ilson`, `ai-order-desk` 등이 있는 팀. 그 팀에 승인된 프로젝트 `ilson-license`를 생성하고 이 작업트리의 `server/license`에 링크했다. Vercel project ID `prj_wOQ9v3bBmlZkY7prIvEU8z12RP26`, 팀 ID `team_7z3aKJgh93Sh4Tfo22djmfC6`.
- 링크 과정에서 CLI가 만든 `.env.local`의 일회용 OIDC 환경 파일은 이 작업자가 제거했다. `.vercel/` 연결 정보는 로컬에만 유지하며 `server/license/.gitignore`가 `.vercel`과 `.env*`를 제외한다. 개인키/운영 시리얼은 아직 생성하지 않았다.
- Marketplace CLI 상품 메타데이터에서 Supabase `free`는 `$0/month`, 지역 `icn1`은 선택 가능했다. 기존 Vercel 팀은 Pro. 실제 Supabase 요금 청구나 계정 상태는 아직 확인하지 못했다.

## 중단 사유와 경계

`vercel integration add supabase --name ilson-license --billing-plan free --meta region=icn1 --no-env-pull --scope jakeparkcoldes-projects --cwd server/license --json`을 비대화형으로 한 차례 실행했으나 종료 코드 1이었다. 출력에 브라우저 및 billing/terms 관련 단어가 감지됐다. 비밀값 유출 방지를 위해 CLI의 전체 출력은 저장하지 않았으므로, 실제 요구가 로그인인지 약관 수락인지 결제 확인인지 확정하지 못했다. 이후 연결된 리소스 조회는 0개였고 Marketplace 설치 목록도 실행 전과 같았다. 중복 생성이나 지시 위반을 피하기 위해 재시도하지 않았다. 총괄에게 Jake의 Marketplace 화면 확인을 요청했고, 정확한 요구는 미확인이라는 정정도 보냈다.

## 아직 하지 않은 일

Supabase 리소스 생성 여부는 프로젝트 연결 목록이 0개라는 사실까지만 확인했다. DB migration, Vercel Secret 설정, 서버 배포와 실제 서버 스모크, 운영 Ed25519 키 생성, 공개키/서버 주소 반영, GitHub prerelease, Jake 시리얼 발급·등록 및 합성 HOME 운영 서버 시험은 하지 않았다. 1기 학생 발급·발송과 Latest 승격도 하지 않았다. Vercel 프로젝트가 존재하므로 같은 이름을 다시 만들지 않는다.

## 다음 행동

1. 총괄/Jake가 Vercel Marketplace의 Supabase 연결 화면에서 실제로 요구되는 로그인·약관·결제 단계와 서울 무료 플랜을 확인하고 필요한 작업을 마친 뒤 신호를 보낸다. 약관·결제는 임의 승인하지 않는다. 총괄의 추가 답이 오면 이미 생성된 리소스가 있는지 확인한 다음 중복 생성 없이 이어간다.
2. Supabase 실제 프로젝트와 접근 수단을 확인하고 `server/license/migrations/001_license.sql`을 적용한다. 필요한 서비스 자격과 관리자 비밀은 값을 출력하지 않고 Vercel Secret으로 설정한다.
3. 배포 및 `/api/health`, 잘못된 시리얼, 관리자 인증 스모크. 사용자 지시의 순서대로 이후 Studio에서 운영 서명 키를 만들고 Vercel 공개키를 반영해 활성화에 필요한 재배포 여부를 확인한다.
4. 공개키·실제 서버 주소를 담은 판을 GitHub **prerelease**로 만들고 Latest는 건드리지 않는다. Jake용 1개만 발급·등록하고 `~/.config/ilson-license/issued/` 같은 0600 파일에만 보관한다. 합성 HOME에서 실제 서버 활성화·status 확인. 원문은 출력하지 않는다.
5. 총괄에게 `[라이선스 배포·Jake 시리얼 준비 완료]`와 서버 URL, Vercel/Supabase 프로젝트 ID, prerelease 태그, 시리얼 파일 경로(값 제외), 시험 결과, 실제 플랜·비용을 보고한다.

## 이어하기 프롬프트

`/Users/koldeumaegmini/orca/workspaces/ilson-box/license-20261106/docs/license-20261106/DEPLOY-HANDOFF-20261106.md`를 읽고 일손 라이선스 배포를 이어가라. Vercel 프로젝트는 이미 만들어졌고 Supabase Marketplace 연동의 브라우저·약관/결제 관련 단계에서 멈췄다. 정확한 요구는 미확인이다. Jake/총괄의 확인을 받은 뒤 기존 리소스부터 확인해 중복 생성을 피하고, 최신 지시의 배포 순서와 비밀값 보호·학생 발급 금지를 지켜라.

## 후속: 관리자 화면 수정

Supabase 연결 대기 중 총괄 지시에 따라 같은 브랜치에 관리자 화면 4건을 반영했다. 상세 시험과 1440/390 전후 캡처는 `ADMIN-WORK-20261106.md`를 참조한다. `template/web/current/pack-library`가 변경됐으므로 배포용 리서치 팩을 현재 템플릿으로 다시 구성하고 릴리스 동등성 검사를 통과해야 한다. 기존 승인 경계(학생 4명 발급·Latest 승격은 별도 신호)는 변함없다.
