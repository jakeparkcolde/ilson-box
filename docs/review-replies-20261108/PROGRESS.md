# 리뷰·문의 답글 초안 작업 기록 (2026-11-08)

- 담당 작업폴더: `~/orca/workspaces/ilson-box/review-replies-20261108`, 브랜치 `feat/review-replies-20261108`, 시작 `121920a`. 총괄 `t3q`.
- 공식 문서 2026-11-08 확인(2.91.0): [목록](https://apicenter.commerce.naver.com/docs/commerce-api/current/get-comments-contents)은 `fromDate`, `toDate`, 1부터 시작하는 `page`, 최대 `size=100`, `contents/totalPages/totalElements` 사용. [답변](https://apicenter.commerce.naver.com/docs/commerce-api/current/create-or-update-answer-contents)은 `PUT /v1/contents/qnas/:questionId`, JSON `commentContent`, 성공 204이며 등록/수정 공용이다. Aside에서 명세를 읽고 해당 탭을 닫았다.
- [인증](https://apicenter.commerce.naver.com/docs/auth) 및 [토큰](https://apicenter.commerce.naver.com/docs/commerce-api/current/exchange-sellers-auth): OAuth client credentials, `client_id_timestamp`를 client secret bcrypt salt로 해싱한 결과를 Base64로 인코딩, POST `/v1/oauth2/token`, bearer 토큰. SELF/SELLER와 계정 권한은 실제 애플리케이션별 확인이 필요하다. 실계정 접근은 금지.
- 원격 조회 직후에도 별도 판매자센터에서 답변이 추가될 수 있다. 조건부 원자 등록은 문서에서 확인하지 못했다. 실제 사용 전 이 위험과 계정 권한, 독립 검수, 1번 승인 저장소 연동 검증이 필요하다.
- 검증 및 변경: 작업 중. 실제 외부 발송·실계정 API 호출 금지. push·배포·main 반영 금지. 승인은 반드시 1번 store가 담당한다.

## 구현과 검증 진행

- 공개 6.4 업데이트 호환 때문에 구현은 `template/lib/replies_*.py` 평면 파일로 배치했다. 6.4 `2e6fd52:tools/update.py`의 `allowed()`로 새 Python 7개와 `template/web/current/replies.js`의 cli/box 양쪽이 허용됨을 직접 확인했다. `tools/update.py`·`build_release.py`는 수정하지 않았다.
- 네이버 연결 준비 버튼은 명시 동의 후 Box `.runtime/venv`에 bcrypt 4.3.0 macOS universal2 wheel만 SHA-256 고정 설치한다. 기본 시스템 Python에 bcrypt가 없음을 확인했고 수동 초안에는 필요하지 않다. 임시 Box에서 설치·합성 인증서명 성공. 기존 업데이트 런타임이 Pillow 등을 쓰는 환경을 재사용하되 bcrypt 설치는 사용자 선택이다.
- 상품 문의의 별도 연결정보와 문의·초안 DB는 Box `.credentials/replies/` 아래 소유자 전용으로 둔다. 기존 snapshot은 `.credentials` 전체를 제외한다. 사용자가 직접 개인정보를 확인해야 하며 자동 가림을 약속하지 않는다. 파일은 자동 삭제되지 않는다.
- 예약 수집은 최초 꺼짐. 사용자가 명시 동의해 예약을 준비한 후 안내한 `ilson start` 또는 멈춤 상태일 때 `ilson resume reply-drafts`를 실행해야 등록된다. `run-job.sh` 고정 분기는 라이선스·시간 제한을 검사하고 도구 없는 Claude로 초안까지만 만든다. 7일 구간별 cursor를 완전히 처리한 뒤 저장하며 중단 시 해당 구간을 재조회한다. 외부 발송이나 승인 요청을 만들지 않는다.
- 승인 계약 모양 가짜 store 시험: 승인 전 차단, 원격 변경/답변, 본문·대상 변조, 계정 변경, 401·403·429, PUT 결과 불명 및 재시작 시 재전송 차단, 중복 페이지, 저장 중복, 예약 재시작, 로컬 원문 표시 경계. 실제 1번 store 통합 및 텔레그램/관리자 양쪽의 같은 원자 전이는 병합 후 재시험해야 한다.
- 로컬 `local_context`는 대상 및 원문 해시가 승인 요청과 일치할 때만 원문을 반환한다. Telegram에서 호출하지 않는 것은 1번 표시 계층의 책임. 로컬 UI는 고객 글을 텍스트로 이스케이프해야 한다.
- 참고 위험: 공식 API는 답변 수정도 수행하며 최종 재조회 이후 다른 판매자의 동시 답변과 PUT 사이 원자 조건부 등록은 확인되지 않았다. 모델과 키워드 검사는 모든 확인 필요 사례나 부정확한 답변을 보장해 식별하지 못한다. 사장님의 검토가 필요하다. 실제 네이버 자격·권한·API, 실계정 및 실발송은 지시대로 시험하지 않았다.
- 1차 전체시험 `python3 -m unittest discover -s tests -v`: 754개 중 실패 2·오류 3·건너뜀 7. 원인: 강의판 내장 파일 재생성 전 두 불일치, Pillow 부재 두 오류, 변경 중 updater 허용목록 불일치 한 오류. 강의 내장 파일을 Python 3.13으로 재생성하고 6.4 경로 배치로 수정했다. Pillow가 있는 격리 경로로 전체 재시험 진행 중(로그 `/tmp/ilson-replies-full-final-20261108.log`).
- 별도 기능 시험은 최신 상태에서 `python3 -m unittest discover -s tests -p test_replies.py -v` 21개 통과. 강의 설치기 시험 6개 중 3개 통과·PowerShell 미설치로 3개 건너뜀. Windows 실기 및 네이버 실계정 시험은 하지 않았다.
- UI 검토: Aside 탭 `http://127.0.0.1:60589/current/index.html?tab=replies`를 열어 표시를 확인하고 탭을 닫았다. 합성 관리자 서버 PID 68728 (2026-11-08 09:34:44 시작, 임시 프로젝트 `/tmp/ilson-replies-ui-fixture-20261108`, 포트 60589)를 식별 후 종료하고 PID 및 포트 해제를 확인했다. 재시작은 새 빈 임시 디렉터리를 만든 뒤 `python3 /tmp/ilson-replies-ui-fixture-20261108.py <빈-임시-디렉터리>`; 운영 서비스·일반 브라우저는 건드리지 않았다.

## 완료 직전 검증 (2026-11-08)

- Pillow 격리 의존성 `PYTHONPATH=/tmp/ilson-license-test-deps python3 -m unittest discover -s tests -v`: 767개 통과, 7개 건너뜀. WebKit 환경 미설정 1, PowerShell 미설치 3, Windows 전용 3. 실행 중 승인 원문 계약과 예약 중복 처리 등 후속 수정을 했으므로, 전체 시험의 기능별 목록은 당시 17개이며 최신 `test_replies.py` 21개는 이후 별도 재실행해 모두 통과했다. 실기 및 실제 1번 store 통합 시험을 대신하지 않는다.
- 예약 수집 재시작은 마지막 완료 시점보다 하루 겹쳐 재조회한다. 저장된 지문이 같은 문의는 기존 조회 범위를 보존해 중복 초안과 불필요한 기존 승인 무효화를 방지한다. 일시적 색인 지연을 완화하지만 모든 플랫폼의 지연을 보장해 포착하지는 못한다.
- 6.4 `2e6fd52` 기준 `check_public --exact-commit`: 합성 리서치 팩을 넣은 시험 묶음에서 차단 36건. 기존 커밋과 다른 신규/변경 내용 및 원본 파일 매칭 32건, 합성 팩의 빠진 공식 전용 파일·정식 manifest 4건. `/tmp/ilson-replies-public-check-20261108/result.txt` 참고. 이는 실제 팩/최종 통합 커밋을 검사한 결과가 아니며 릴리스 검사는 통합에서 다시 필요하다. 검사 뒤에도 기능 코드를 보완했으므로 이 시험 묶음은 최종 산출물이 아니다. 가드는 끄지 않았다.
- Aside 스킬 지시에 따라 이 기기의 Aside CLI를 1.26.1104.1843에서 1.26.1107.24로 갱신했다. 해당 작업에서 연 탭과 로컬 시험 서버는 모두 닫았다.
