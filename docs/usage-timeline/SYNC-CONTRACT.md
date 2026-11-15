# SYNC-CONTRACT v1 — Box ↔ course site

2026-11-15 KST · owner t2v5 · 구현자 간 고정 계약. base URL은 config의 사이트 origin+배포 prefix(예 `https://example.invalid/learn`), 기본 빈 값=네트워크 OFF. 아래 경로를 base에 연결한다. 운영 URL/시리얼/hostname/계정 cookie 하드코딩 금지. 모든 응답 Cache-Control: no-store. JSON, UTF-8, 최대 1 MiB. 알 수 없는 키/중복 JSON 키/NaN/Infinity 거절. 에러는 `{ "error": "INVALID_PAYLOAD" }` 같은 고정 enum만, 원 body/코드/토큰은 로깅 금지.

## 로그인 사이트 → 일회 코드 → 기기 자격
1. 로그인된 수강생이 사이트에서 본인 enrollment/cohort·Jake 수신·필드·기간·privacy-v1을 보고 명시 동의한다. 사이트 `POST /api/activity/link-codes` (사이트 세션+CSRF, body `{ "enrollment_id": UUID, "consent_version": "usage-v1" }`) → 201 `{ "code": "12자리 대문자 영숫자", "expires_at": "UTC ISO8601" }`. TTL 10분, hash만 저장, 1회, subject/IP rate-limit. 한 학생의 지정 활성 기기는 1대; 기존 활성 기기 있으면 409 DEVICE_ALREADY_LINKED. 다른 enrollment도 자동 합산하지 않는다. 미성년/회사 직원/공동 계정은 v1 사이트에서 연결 거절.
2. Box 미리보기 확인 뒤 `POST /api/activity/link` (무인증, body 정확히 `{ "schema_version": 1, "code": CODE, "device_id": UUID, "consent_version": "usage-v1" }`). code는 query/argv 로그에 노출하지 않는다. 서버가 코드에서 subject/cohort를 확정한다. 응답 201 정확히 `{ "device_token": "32자 이상 URL-safe 난수", "device_id": UUID, "enrollment_id": UUID, "consent_id": UUID, "expires_at": "UTC ISO8601", "retention_days": 60 }`. token TTL 90일, hash 저장, scope=upload/status/revoke-delete 해당 device만. 성공 후 code 폐기. 네트워크 실패 후 같은 code+device_id 재요청은 서버가 이전 자격을 재발급(이전 토큰 무효화)할 수 있도록 10분 이내 idempotent. 다른 device 재사용 409. rate-limit 실패 429. 기기는 token을 0600 private 파일에만 저장, 절대 출력/export 금지. 사이트 세션/관리자/service-role 자격 기기로 복사 금지.

## 업로드
`PUT /api/activity/batches`, Authorization: Bearer DEVICE_TOKEN. body는 아래 필드만:
```
{
  "schema_version": 1,
  "aggregation_version": "usage-v1",
  "device_id": "UUID",
  "enrollment_id": "UUID",
  "consent_id": "UUID",
  "timezone": "Asia/Seoul",
  "revision": 1,
  "daily": [
    {"date":"2026-11-15","tool":"claude_code","model":null,
     "sessions":1,"turns":2,"input_tokens":null,"output_tokens":null,
     "cache_read_tokens":null,"cache_creation_tokens":null,"quality":"observed"},
    {"date":"2026-11-15","tool":"claude_code","model":"claude-sonnet-4-5",
     "sessions":0,"turns":0,"input_tokens":100,"output_tokens":40,
     "cache_read_tokens":20,"cache_creation_tokens":0,"quality":"observed"}
  ]
}
```
`schema_version` int=1; aggregation_version literal. UUID canonical lowercase random v4 (hardware-derived 금지). timezone 유효 IANA 최대 64자; enrollment/consent는 서버 자격과 같아야 함. revision 정수 1..2^53-1, 장부 변경마다 단조 증가, 재시도는 같은 revision/body. 최대 4096 daily rows, 날짜는 YYYY-MM-DD, 미래 날짜 거절(기기 timezone 오늘), 최근 366일 범위. tool enum `claude_code|codex`(Codex는 Box 준비 중). model은 null 또는 버전 관리 allowlist: `claude-sonnet-4-5`, `claude-sonnet-4-6`, `claude-opus-4-1`, `claude-opus-4-5`, `claude-opus-4-6`, `claude-haiku-4-5`; Codex 추후 계약 버전 확장. 날짜 접미 ID는 기기가 이 base ID로 정규화, 미지원 null. 임의 free-text 모델 문자열 금지.

sessions/turns는 0..2^53-1 정수. **null model 행만 세션/turn 보관**: 첫 관측 날짜에 세션당 1회, 사용자가 보낸 고유 user message당 turn 1회. model 행은 sessions=turns=0, assistant별 비중복 토큰만 보관. null model은 미지원 모델 토큰도 담을 수 있다. 따라서 모델 행과 null 행을 더해도 세션/turn 중복 없음. 날짜 간 세션도 중복 없음. 모델별 세션/turn 추정 금지. 같은 세션의 여러 날짜 사용은 다음 날짜에 turn/tokens만 올라간다. 활성 날짜는 sessions>0 OR turns>0 OR 명시 토큰>0. token counters는 각 0..2^53-1 또는 null(미지원/누락); null≠0. Claude 입력은 noncached input, cache 별도. quality enum `observed|partial`; 실제 무관측 날짜는 row 자체 없음(0건으로 생성 금지). 일부 필드가 null이어도 정상 null 모델 집계행의 cache/token 부재는 partial 이유가 아님. unknown/오류는 summary의 별도 local partial 상태, 날짜를 특정할 수 있으면 해당 날짜 행 quality partial. 가격/비용/본문/제목/파일명/경로/프로젝트명/hostname/username/원 session ID/분 단위 timestamp는 **보내지 않는다**. 서버 추정 비용은 동일 가격표 출처/확인일을 표시해 계산한다. `generated_at` 등 자유 메타도 없음.

업로드는 기기 장부의 현재 snapshot이다. key=(consent_id,device_id,date,tool,model-null-sentinel). 서버는 device를 잠가 동의/철회/만료를 확인한 같은 트랜잭션에서 revision 판정 후 모든 row upsert, 누락된 이전 row는 삭제(366일 장부 교체). 같은 revision+동일 canonical JSON hash → 200 재시도 성공, 같은 revision 다른 body → 409 REVISION_CONFLICT, 낮은 revision → 409 STALE_REVISION, 높은 revision → 대체. revision 1부터 시작할 의무는 없음. rows를 합산 INSERT 하지 않는다. 응답 정확히 `{ "accepted_revision": INT, "accepted_rows": INT, "delete_after": "UTC ISO8601" }`.

## 상태/철회/삭제
`GET /api/activity/me` Bearer → 200 `{ "device_id": UUID, "enrollment_id": UUID, "consent_id": UUID, "expires_at": ISO, "last_revision": INT, "delete_after": ISO|null }` (본문/타 학생 없음).
`POST /api/activity/revoke` Bearer body 정확히 `{ "device_id": UUID, "delete_data": true }` → 200 `{ "revoked": true, "deleted": true }`. 한 트랜잭션으로 해당 consent/device 업로드 자격 폐기+usage rows/파생 집계 삭제+tombstone 생성. 같은 토큰 재요청도 200 동일 응답(토큰 hash와 삭제 tombstone만 보관, 삭제 권한 이외 사용 불가). 삭제 미완료면 202 `{ "revoked": true, "deleted": false }`; Box revoke_pending 유지. 서버 401이 삭제 완료를 뜻하지 않음. 사이트 세션 본인용 `DELETE /api/activity/me`는 해당 본인 enrollment의 기기/자료 전체 철회·삭제, body `{ "enrollment_id": UUID }`, 같은 완료 응답. Box는 DELETE 대신 위 scoped revoke 사용.

unlink는 즉시 로컬 sync 비활성, credential은 revoke 재시도 전용으로만 남김. 서버 삭제 확인 후 credential 지우고 새 random device_id 생성; 다음 연결은 새 consent다. 삭제 후 stale upload는 410 CONSENT_REVOKED, 절대 재생성 불가. 업로드 401/403/410이면 자동 upload 중지(설명 상태), 삭제 요청을 완료로 오인하지 않음. 연결 해제/삭제 실패는 사용자에게 대기 상태와 사이트 본인 삭제 경로를 안내.

## 보관/운영/재시도
로컬 ledger 최근 366일. 서버 usage row TTL=min(그 device 첫 수신+60일, 확인된 강의 종료+60일); row 수정/재전송은 first_received_at/delete_after 연장 금지. 만료 날짜 row는 재수신해도 부활 금지(만료 tombstone 또는 기간 high-water). 삭제/철회 token hash tombstone은 토큰 만료+7일, 최소 동의/접근 audit는 90일 후 삭제(원 body/코드/token/IP 없음). 암호화 백업 최대 30일; 복원 시 tombstone 재적용 완료 전 서비스 오픈 금지. TTL job 매일, 실패 관리자 경고. 실제 운영 검증/정책 공개는 배포 게이트.

네트워크 timeout 3초, 한 tick 최대 한 요청; 408/429/5xx/연결 실패는 60초×2^attempt 최대 6시간 + jitter, Retry-After가 유효하면 최대 6시간 범위 반영. 성공 후 최소 10분 간격. 400/404/409/422는 자동 업로드 중지하고 재연결/버전 점검 안내, 401/403/410도 자동 중지. 응답/예외 원문 노출 금지. CLI `sync` 명시 실행도 backoff 존중. 로컬 수집 OFF 또는 base URL 없음은 네트워크 0회(별도 unlink 삭제 재시도는 사용자 요청/기록된 revoke_pending에 한함).

HTTPS 필수; 테스트 전용 loopback http(127.0.0.1/localhost/::1) 허용. redirects/프록시 상속 없이 Authorization 전송 범위 고정, URL userinfo/query/fragment 거절. 서버 anon/authenticated/public 직접 테이블 권한 전부 revoke, service-role handler에서 매번 student/cohort/consent 검증. 강사 비교는 Jake usage scope만, 학생 간 비교 비공개. no-consent/no-data/stale/partial을 0 사용과 구분하고 도구 중립 지표만 비교한다.
