# Windows 큐레이터 최초 상태 조회 수정 · 2026-11-14

기준 `d25b333`, branch `fix/windows-curator-20261114`. 지정 워크트리의 단독 작성 작업이다. push/Release/실제 노트북 접근/AGY 실행은 하지 않는다.

## 원인과 변경

기존 Windows `directory()`는 없는 디렉터리의 `CreateFileW` 실패와 마지막 `is_dir()` 실패를 모두 `UNSAFE_PATH`로 변환했다. 최초 설치에는 `state/curator/<볼트 해시>`가 없으므로, 없는 설정을 기본 off로 해석하는 `load_json()`의 `FileNotFoundError` 처리가 작동하지 않았다. macOS의 디렉터리 열기는 이미 해당 예외를 보존했다.

- 읽기용 디렉터리는 `lstat()`의 누락 예외를 보존한다. Win32 열기와 경합 중 사라져도 `ctypes.WinError()`가 누락 예외로 매핑한다. 상태 조회는 off를 반환하고 상태/볼트 디렉터리를 만들거나 노트를 열지 않는다.
- 처음 `--off`와 동의한 `--on`은 상태/잠금 디렉터리를 안전하게 만든다. 세 판본 모두 동일한 정책이다. 없는 선택 입력 폴더는 빈 입력이며, 실제 볼트 자체가 없으면 `PATH_MISSING`이다. 기존 빈 볼트의 `journal/curator`와 비공개 staging은 첫 실행에서 생성한다.
- Windows의 각 조상 핸들은 기존과 같이 metadata 접근, `FILE_SHARE_READ | FILE_SHARE_WRITE`만 허용하고 `FILE_SHARE_DELETE`를 주지 않는다. `BACKUP_SEMANTICS | OPEN_REPARSE_POINT`, 전후 경로 검사, ACL 검사와 역순 핸들 해제를 유지한다. POSIX `O_NOFOLLOW`도 유지한다.
- 오류는 경로나 OS 예외 원문 없이 원인 코드로 출력한다. 누락 `PATH_MISSING`, 디렉터리 아님 `PATH_NOT_DIRECTORY`, 공유 위반 `SHARING_VIOLATION`, 잠금 위반 `LOCK_VIOLATION`, 권한 거부 `ACCESS_DENIED`, 링크 `PATH_SYMLINK_UNSUPPORTED`, junction/마운트 재분석 지점 `PATH_MOUNT_POINT_UNSUPPORTED`, 기타 재분석 지점 `PATH_REPARSE_UNSUPPORTED`를 구분한다. 비경로 검증 오류는 기존 정책을 유지한다. offline/recall 표시에는 `OFFLINE_FOLDER_UNSUPPORTED`·`OFFLINE_FILE_UNSUPPORTED`를 사용한다.
- `course/install_payload.py`에 정확한 d25b333 curator/bootstrap 해시를 추가해 기존 설치본의 안전한 갱신과 rollback을 허용한다. 사용자 수정본은 교체하지 않는다. 두 설치기의 payload와 bootstrap은 정식 packer로 재생성하며 stdin 전달을 유지한다.

## OneDrive 선택과 공식 근거

이번에는 브리프가 허용한 **보수적 차단**을 선택한다. Cloud Files 재분석 지점을 통과시키지 않는다. 실제 Windows에서 hydration, 파일 핸들 경합, ACL을 검증하지 않은 상태에서 태그만 허용하면 기존 경로 보호와 오프라인 원칙을 약화시킬 수 있기 때문이다. 완전히 로컬로 고정한 파일이라도 클라우드 재분석 태그가 남아 있으면 차단한다. 이름에 OneDrive가 있다는 이유만으로 일반 로컬 폴더를 차단하지는 않는다.

[Microsoft MS-FSCC 재분석 태그 표](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fscc/c8e77b37-3909-4fe6-a4ea-2b9d423b1ee4)를 Aside로 직접 확인했다. `IO_REPARSE_TAG_CLOUD`는 `0x9000001A`, `_1`부터 `_F`는 `0x9000101A`부터 `0x9000F01A`까지이며 각 단계가 `0x1000`이다. 16개를 정확한 집합으로 진단한다. `IO_REPARSE_TAG_MOUNT_POINT`는 `0xA0000003`, `IO_REPARSE_TAG_SYMLINK`는 `0xA000000C`다. 표의 `IO_REPARSE_TAG_ONEDRIVE` (`0x80000021`)는 미사용 항목이며 허용 목록으로 삼지 않는다.

볼트/상태의 조상이 Cloud Files 재분석 폴더이면 `CLOUD_FOLDER_UNSUPPORTED`로 멈추며, 파일은 `CLOUD_FILE_UNSUPPORTED`로 본문을 열기 전에 차단한다. 한국어 오류 안내는 동기화 밖의 로컬 볼트와 상태 폴더를 사용하도록 설명한다. 허용 입력 아래에 있는 재분석 파일/폴더는 기존 제외 건수에 포함되며 본문을 열거나 하위 폴더를 열거하지 않는다. 차단된 루트에 대해서는 수집 자체를 시작하지 않으므로 읽음 건수를 만들어 내지 않는다.

강의판 사용자는 필요한 노트를 동기화 밖의 로컬 볼트에 직접 준비하고 `ILSON_COURSE_VAULT`를 그 폴더로 지정한다. 상태 위치도 동기화 밖이어야 하며 강의판은 `ILSON_COURSE_STATE`로 선택할 수 있다. 이 변경은 Documents Known Folder로 자동 이동하지 않으며 설치기와 큐레이터의 기존 기본 위치 선택을 유지한다. full Mac판은 일반 로컬 Box home 아래 `vault`를 사용한다. 큐레이터는 클라우드 파일을 내려받거나 폴더를 옮기지 않는다.

[Microsoft 파일 속성 표](https://learn.microsoft.com/en-us/windows/win32/fileio/file-attribute-constants)는 `REPARSE_POINT=0x400`, `OFFLINE=0x1000`, `RECALL_ON_OPEN=0x40000`, `RECALL_ON_DATA_ACCESS=0x400000`을 정의한다. 마지막 속성은 파일 읽기나 디렉터리 열거가 원격 내용을 가져올 수 있음을 뜻하므로, 재분석 지점 외의 recall/offline 표시도 별도로 점검한다. `RECALL_ON_OPEN`과 EA는 값이 겹치므로 전자는 디렉터리 항목 열거에서만 차단하고, 일반 `stat`의 EA는 허용한다.

## 검증 기록과 남은 일

- 초기 집중 회귀: 기존 curator 23건 + 새 경로/강의 설치 회귀 10건 = 33건, 실패 0. 로그 `.scratch/curator-windows-fix/focused.log`.
- 모의 Win32는 실제 Windows API가 아니다. macOS에서 Win32 디렉터리 순회만 fake kernel/ACL로 바꾸고 실제 임시 디렉터리·JSON·잠금·출력 코드를 실행한다. `WinError`의 예외 형식도 모의한다. 실제 PS5.1, Win32 공유 모드, ACL, OneDrive 동작은 별도 노트북 재시험이 필요하다.
- 두 설치기 내장 payload의 실제 stdin bootstrap으로 임시 설치한 다음 `ilson curator --status` exit 0/off, 미존재 상태/볼트 보존을 macOS에서 확인했다.
- 최종 집중 시험: curator 35건 OK (`focused-final-0.log`), course 61건 OK/skip8 (`focused-final-1.log`), 각 exit0. 실제 d25b333의 9개 helper를 seed한 갱신/rollback과 curator 사용자 편집 보존을 포함한다. 초기 강의 회귀는 구판 fixture가 새 해시 항목도 구판에 존재한다고 가정해 실패했으며, 구판의 실제 파일 집합으로 수정했다. 확대된 안내 문구를 지나치게 제한하던 테스트 조건도 정리했다. 실패 로그는 `.scratch/curator-windows-fix/pre-final-*`로 보존했다.
- 전체 suite: `python3 -m unittest discover -s tests -v < /dev/null` — **943건 실행, 903 PASS, 40 skip, 실패 0, exit0**, 352.569초. 로그 `.scratch/curator-windows-fix/full-0.log`, 종료 기록 `full-exit.json`. 브리프의 main 930건에 새 회귀 13건이 추가되었다.
- 집중 hc 프로그램 t358, t359, t35b는 결과 확인 뒤 제거했다. 전체 시험 t35c (`curator-win-full`)도 exit0 결과를 확인하고 제거했다. PID/PGID 78256, 시작시각 2026-11-14 02:29:30 KST였으며 종료 뒤 해당 프로세스 그룹이 비었음을 확인했다. preview/server/AGY/하위 에이전트는 시작하지 않았다.
- Aside `repl`로 Microsoft 두 페이지와 Google 검색을 확인했다. 명시적으로 연 탭은 각 스크립트의 `closeTab()`으로 닫았고 오류로 종료된 일회 세션의 잔여 대상도 목록에서 없음을 확인했다. 사용자 기존 탭은 보존했다.

## 이어가기 프롬프트

`docs/windows-curator-fix-20261114.md`와 지정 FIX-BRIEF를 읽고 `fix/windows-curator-20261114`의 작업을 이어가세요. 기준은 d25b333이며 단독 writer입니다. 첫 상태 누락 처리와 경로 없는 오류 코드를 수정했고 OneDrive는 명확한 안내와 함께 보수적으로 차단합니다. 모의 Win32와 실제 macOS stdin 설치 테스트를 구분하세요. 집중·전체 시험 결과를 확인하고 커밋한 뒤 외부 `agy-fix-curator-review/BRIEF.md`와 `target.diff`(d25b333..HEAD)를 준비하여 총괄 t2v5에 한국어 hc 보고하세요. push/Release/노트북 접근/AGY 실행과 chmod/rm/sudo/chown은 금지입니다. 소유 test terminal만 결과를 확인하고 정리하세요.


## 최종 패키징과 마감

- 양 payload 62,012자, 9 helper/compile/bootstrap 원본 일치, 두 curator 원본 일치, stdin 전달 유지, bash syntax, `git diff --check` PASS. 기록 `.scratch/curator-windows-fix/packaging-check.json`.
- Windows 설치기 SHA-256 `edd0d1dc1bd216dc081847ce0c120f0dda04b9a45986252da700c3d603a5a542`.
- Intel 설치기 SHA-256 `6d18b6948d2510db54655c0fed62c8882a089ac0d02b2462a5c871748dcb6636`.
- 이 최종 기록만 전체 suite 뒤에 추가했다. 제품 코드와 payload는 전체 시험 시작 이후 변경하지 않았다.
- AGY 전달 묶음은 총괄의 `handoffs/work/2026-11-13-ilson-box-curator-installlog/agy-fix-curator-review/`에 BRIEF.md와 실제 `d25b333..HEAD` target.diff로 준비한다. 최종 commit/diff 해시는 외부 BRIEF에 기록한다. 검토와 병합·후속 Windows 재시험은 총괄이 담당한다.
- Close-out 2026-11-14: 소유 시험 터미널 t358/t359/t35b/t35c를 결과 확인 후 제거했다. 전체 시험 프로세스 그룹 종료를 확인했고, Aside 조사 탭은 모두 닫았으며 마지막 목록에서도 Microsoft 조사 탭이 없었다. preview/server/자동화 Chrome/AGY/하위 에이전트 미시작. 사용자 기존 탭과 서비스는 보존했다. 미디어 산출물이 없어 My Book archive 해당 없음. 재시작할 서버 없음.
- 시험 재실행: `python3 .scratch/curator-windows-fix/run-checks.py focused-final` 또는 `python3 .scratch/curator-windows-fix/run-checks.py full`. 일반 호출은 위 unittest 명령을 쓴다.
- 남은 승인 경계: 실제 Windows/PS5.1/ACL/OneDrive는 미검증이며 별도 권한의 노트북 재시험이 필요하다. push/Release/운영환경 변경을 하지 않았다.
