# Windows 버전·손상 이력 수정 · 2026-11-14

- 목표: Windows 설치 성공 이력이 버전 숫자 제한 때문에 사라지는 문제를 고치고 손상 로그를 설치 중단과 구분한다.
- 지정 작업: `fix/windows-version-20261114`, 기준 `a30b50a`, 이 워크트리 단독 작성. commit과 AGY 읽기 전용 검토 묶음까지 준비한다. push·Release·노트북 접근·AGY 실행은 하지 않는다.
- 재현: 실제 복사 JSONL SHA-256 `be127fa74ae6c938cb1229049af5fd830d014c5120afaeee363c11856a397b2b`, 28줄 모두 JSON 파싱 가능. 기준 코드 `validate_event`에서 28/28 거부. `shell_version=5.1.26100.9818`의 빌드 숫자가 원인이다. 원문 바이트는 변경 없이 로컬 scratch에서 시험했다.
- 수정: `template/lib/install_diagnostics.py`의 `VERSION_PATTERN`을 단일 원본으로 사용한다. 점으로 구분한 ASCII 숫자 2~4묶음, 묶음당 1~6자리와 `missing`·`unknown`만 허용한다. 임의 접미사·자유 문장·줄바꿈은 가린다. 실제로 필요한 비숫자 빌드 접미사는 관찰되지 않아 추가하지 않았다.
- 생성: `python3 tools/pack_diagnostics.py`가 shell·PS 기록기, schema, 강의 helper와 bootstrap 내장본을 맞춘다. `python3 course/pack_course.py`가 강의 payload와 bootstrap을 갱신한다. 기존 stdin 전달을 유지한다. PowerShell 기록기는 셸 버전과 OS 버전을 같은 규칙으로 정제한다.
- 읽기: 잘못된 버전은 해당 필드만 `unknown`으로 바꾸고, 선택 메타데이터는 정제한 뒤 이벤트를 보존한다. 필수 lifecycle 필드가 깨지거나 JSON/TSV 자체를 해석할 수 없으면 다른 유효 이벤트를 유지하고 `damaged / log_status=malformed / exit 3`을 반환한다. 모든 줄이 깨진 경우도 선택 run ID와 가린 공유 요약을 보존한다. 실제 실행 중·종료 이벤트 없음은 `interrupted`, 사용자 확인 대기는 `pending / exit 4`다.
- 실로그 검증: 동일한 28줄에서 28/28 이벤트 보존, `pending / exit 4`, 원래 run ID 보존. `--share` 출력도 생성·읽기 확인. 검증 결과는 `.scratch/windows-version-fix/real-replay-result.json`에 보존했다. 운영 노트북에서 실행한 결과가 아니다.
- 신규 회귀: `tests/test_diagnostic_versions.py` 8건, 7 PASS·1 skip. Windows `5.1.26100.9818`·`10.0.26100`·`7.4.6`, macOS `26.6.2`, 허용 범위 경계, 잘못된 필드, JSONL·TSV 손상, 모든 줄 손상, 공유 정보 가림, 독립 doctor, 내장본 일치를 검사한다.
- 미검증: 이 환경에 pwsh가 없어 PowerShell 실행 회귀를 skip한다. 실제 Windows PowerShell 5.1·PS7·Windows ACL·사람의 창 확인은 별도 담당자의 실기기 시험에 남긴다. Mac 회귀로 이를 통과했다고 주장하지 않는다.
- 검증 파일: `.scratch/windows-version-fix/version-tests.log`, `diagnostics-tests.log`, `full-suite.log`, `full-suite-exit.txt`. 전체 suite는 `python3 .scratch/windows-version-fix/run-full-suite.py`로 실행하며 stdin을 DEVNULL로 둔다.
- 전체 회귀: 930 tests, 890 PASS·40 skip, 실패/오류 0, exit 0 (361.956초). 기존 조건부 생략에 신규 PowerShell 실행 회귀 1건이 추가됐다.
- 최종 focused: 버전 회귀 8건 OK(skip1), 기존 진단 18건 OK. 전체 suite 실행 중 보강한 schema 줄바꿈 guard·독립 doctor 손상 표시는 최종 focused에서 재검증했다.
- 정적 검증: shell syntax, PS ASCII/BOM, 생성기 재실행 byte 일치, 내장 기록기·payload parity, 새 문서 private path/host 검사, `git diff --check` PASS.
- 설치기 SHA-256: Windows `1a3ea0a6351462511350be531fbacd575b8c117324430c23b5694f4e043f91b9`, Intel `22fa231afa6b6f7a6a615b329ba2c6937350c3e34406b8bed865de8d0d2599db`.
- Close-out 2026-11-14: 소유 hc test terminal `t349` (`windows-version-suite`) exit 0과 suite PID 종료를 확인한 뒤 제거했다. 브라우저·preview·별도 에이전트는 시작하지 않았고 테스트용 임시 서버는 suite 수명 안에서 종료됐다. 다른 세션·생산 서비스는 보존했다. 완성 미디어가 없어 archive 대상은 없다. 재실행 명령은 위 suite 명령이며 preview 재시작은 해당 없다.
- 전달: 지정 브랜치에 commit하고 외부 `agy-fix-version-review/BRIEF.md`와 `target.diff`에 최종 SHA·기준 대비 전체 diff를 기록한다. AGY 검토와 별도 Windows 실기기 시험, 병합/배포 판단은 총괄에게 남긴다.

## 이어가기 프롬프트

FIX-BRIEF-windows-version.md와 이 기록을 읽고 `fix/windows-version-20261114`의 최종 commit 및 `agy-fix-version-review/`를 확인하세요. 단독 구현과 실복사 로그 재현은 끝났습니다. 전체930건 OK(skip40)와 소유 test terminal 정리는 완료됐습니다. 총괄 t2v5가 AGY 읽기 전용 검토 및 별도 Windows 실기기 재시험을 관리하세요. push·Release·노트북 접근·AGY 실행은 이 작업자의 범위 밖입니다. 다른 writer와 같은 워크트리를 공유하지 마세요.
