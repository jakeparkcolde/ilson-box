# Windows payload 전달 수정 · 2026-11-14

- 지시: FIX-BRIEF-windows-payload.md, 한국어 hc send t2v5 보고. 지정 branch fix/windows-payload-20261114, 기준 e9e41a31709001a8e459211544dc8e1166cee727, 이 worktree 유일 writer.
- 범위: Windows·Intel 강의 bootstrap/payload 표준입력 전달, helper 실제 실행 실패 분류·종료 코드·Windows 허용 예외 클래스 기록, full Mac helper 실패와 실제 중단 구분.
- 경계: push/Release/노트북 접근/AGY 실행 없음. 직접 chmod/rm/sudo/chown 없음.
- 관찰: 기준 Windows payload 42,088자는 설치기가 넣던 단일 환경 변수의 32,767자 제한을 넘는다. 실제 노트북 실패 시 예외 원문/실행 여부는 기록되지 않아 원인 확정은 별도 실기기 재시험에 남김.
- 구현: bootstrap 1줄과 base64 payload를 stdin으로 전달. 고정 짧은 Python 명령만 사용하며 payload 환경 변수·인자·임시 파일 없음.
- 진단: Windows Python 미존재만 DEPENDENCY_FAILED 생략. 실행 실패는 failed/EXECUTE_FAILED와 실제 native code; 예외는 exit_code=null/exit_source=exception, 고정 allowlist exception_class. PS5.1 native stderr가 LASTEXITCODE 포착 전에 예외가 되지 않도록 제한된 구간에서 preference 복원. Intel bootstrap/wrapper native code와 conflict 구분. full Mac helper 명령 실패는 EXECUTE_FAILED, signal은 INTERRUPTED 보존.
- 검증 완료: course 50건 OK(skip8); diagnostics 18건 OK; bash/sh syntax 및 git diff --check PASS.
- 미검증: 실제 Windows5.1/PS7 실행, Windows ACL; pwsh 없음. 새 Windows helper-stage 회귀는 skip이며 실기기 담당자에게 전달.
- 실행: hc terminal t33t (windows-payload-suite), python3 .scratch/windows-payload-fix/run-full-suite.py. 전체 suite log .scratch/windows-payload-fix/full-suite.log, exit 파일 full-suite-exit.txt. 전체 889건/850 PASS/39 skip, exit 0(385.877초).
- 브라우저/preview/장기 서비스 미시작. 완성 미디어 없음(archive 대상 없음).
- 다음: 전체 결과 확인 → focused diff 확인 및 commit → agy-fix-windows-review/BRIEF.md + target.diff(e9e41a3..HEAD) → t2v5 보고 및 소유 test terminal 정리.

## 최종 검증과 마감

- 전체 suite: 889건 실행, 850 PASS, 39 skip, 실패 0, exit 0. skip은 기존 조건부 38건 + 새 Windows helper-stage 회귀 1건.
- 마지막 Windows 함수 범위 수정 뒤 최종 전달 회귀 5건 OK(skip1), Windows 정적 내장본 검사와 exception schema allowlist 일치 각 1건 PASS, shell syntax 및 diff whitespace PASS. 로그: .scratch/windows-payload-fix/transport-final.log, windows-static-final.log, exception-schema-final.log.
- Windows 설치기 SHA-256: 17effac32256c11b56f02df417e63f2fb3a87e3118da209721cad74ee6121747. 새 payload 42,264자, bootstrap 7,944자.
- AGY 전달: /Users/koldeumaegmini/orca/projects/Studio_base/handoffs/work/2026-11-13-ilson-box-curator-installlog/agy-fix-windows-review/BRIEF.md, WINDOWS-RERUN.md, target.diff(e9e41a3..최종 HEAD). commit id는 외부 BRIEF의 완료 기록에 남김.
- Close-out 2026-11-14: 소유 suite terminal t33t exit 0 확인 후 제거. 실행 중 테스트/preview/browser/server 없음. 다른 세션/생산 서비스 보존. 완성 매체 없음, My Book archive 해당 없음.
- 재실행: python3 .scratch/windows-payload-fix/run-full-suite.py (stdin은 하네스에서 DEVNULL). 브라우저·preview 재시작 명령은 해당 없음.
- 남은 일: 총괄의 AGY 읽기 전용 검토와 별도 Windows5.1 실기기 재시험, 승인 뒤 병합/배포 판단. 이 작업자는 push/Release/노트북/AGY 접근하지 않음.

## 복사할 이어가기 프롬프트

FIX-BRIEF-windows-payload.md와 agy-fix-windows-review/BRIEF.md를 읽고 지정 branch의 수정 결과를 검토하세요. 구현은 완료됐고 전체889건 OK(skip39)이며 pwsh/실제Windows 검증은 미실행입니다. 총괄 t2v5가 AGY 읽기 전용 검토·별도 노트북 worker의 WINDOWS-RERUN.md 실행을 관리하세요. 새 curator worker는 수정 commit 위로 rebase하고 payload/기록기를 재생성해야 합니다. push/Release는 별도 승인, 이 worktree를 다른 writer와 공유하지 마세요.
