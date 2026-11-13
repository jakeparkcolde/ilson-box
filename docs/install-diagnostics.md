# 로컬 설치 진단 · ILSON-DIAG-1

이 문서는 검수 중인 소스의 기능을 설명합니다. 공개 Release나 기존 설치자에게 배포됐다는 뜻은 아닙니다. 강사 실시간 보고·자동 업로드는 포함하지 않습니다.

세 설치기는 Python이나 일손 명령이 없어도 첫 실행 구간부터 이력을 남깁니다. 전체판 `ilson setup`을 직접 실행해도 기록하며, 설치기에서 호출하면 같은 run의 하위 구간으로 남깁니다. Mac은 ASCII TSV(환경의 고정 숫자/열거값·boolean만 포함), Windows는 BOM 없는 UTF-8 JSONL입니다. 파일 준비, 명령 실행, 사람이 해야 할 로그인·업무 가동을 구분합니다.

```sh
ilson --version
ilson doctor --install
ilson doctor --install --share
ilson doctor --install --json
```

이 doctor는 라이선스·AI 로그인·네트워크가 필요 없습니다. 기본 `ilson doctor`는 전체판의 기존 네트워크/Box 점검을 유지합니다. 로그와 지원 파일에는 시리얼·토큰·이메일·사용자명·노트·자유로운 오류 원문·PATH 원문을 넣지 않습니다. 허용하지 않은 오류 상세는 `DETAIL_SUPPRESSED`로 처리합니다. URL 대신 공식 호스트 분류와 curl/HTTP 오류 코드를 남깁니다. DNS, HTTP 실패, timeout, TLS 실패와 실행 실패를 구분하며 TLS 설정이나 프록시를 자동 변경하지 않습니다.

기본 저장 위치는 Mac `~/.ilson-diagnostics/runs/`, Windows `%LOCALAPPDATA%\ilson-diagnostics\runs\`입니다. `ILSON_DIAGNOSTICS_DIR`는 시험·명시적인 별도 저장 위치입니다. 링크/reparse point나 안전하지 않은 저장 경로는 거절합니다. `LOG_UNAVAILABLE`이면 성공 이력이 저장됐다고 해석하지 마세요. 최근 30일·최대 20 run·10 MiB 범위로 다음 실행 때 정리하며, 활성 run과 알 수 없는 파일은 자동 삭제하지 않습니다. 지원 파일도 30일 기준으로 정리합니다. 중단·마지막 줄 파손·종료 이벤트 없음은 결과 미확인입니다. 옛 설치에서 기록하지 않은 과거 실패는 복원할 수 없습니다.

`--share`가 표시하는 `IL-...`은 **로컬 파일의 참조번호**입니다. 참조번호만 보내면 강사가 내용을 볼 수 없습니다. `share/`의 TXT/JSON을 직접 검토한 뒤 필요한 파일을 문의 채널에 첨부하세요. 이 명령은 아무것도 전송하지 않습니다.

## 현재 창과 새 창

설치 자식 프로세스가 PATH를 바꿔도 이미 열린 부모 창은 바뀌지 않습니다. 설치기가 표시한 실제 run ID가 든 두 줄을 각각 실행하세요.

Mac 현재 창:

```sh
export PATH="$HOME/.local/bin:$PATH"; ilson doctor --install --confirm-shell current --run <설치기가 표시한 run ID>
```

실제로 새 창을 연 뒤:

```sh
ilson doctor --install --confirm-shell new --run <설치기가 표시한 run ID>
```

새 창 여부는 사용자의 선언에 의존합니다. 절대 경로로 실행한 설치기 자체 점검과 구분합니다. 전체판 복구 경로는 `"$HOME/.ilson-cli/ilson" doctor --install`, Intel 강의판은 `"$HOME/.local/bin/ilson" doctor --install`입니다. 명령 이름이 다른 설치본을 가리키면 확인으로 세지 않습니다.

Windows 현재 창은 설치기가 표시한 다음 형식입니다.

```powershell
$env:Path=[Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User'); ilson doctor --install --confirm-shell current --run <표시된 run ID>
```

새 창은 같은 `--confirm-shell new` 명령입니다. 명령을 찾지 못하면 `& "$env:LOCALAPPDATA\ilson-course\bin\ilson.cmd" doctor --install`로 점검합니다.

Mac에서 초기화 파일 실행을 명시적으로 허용하고 login/non-login 셸을 모의 점검하려면 `ilson doctor --install --simulate-shell zsh --run <run ID>` 또는 `bash`를 사용합니다. 각 셸에 5초 제한이 있으며 실제 새 창 확인을 대신하지 않습니다. 기본 doctor는 이 초기화 파일을 실행하지 않습니다.

작업 폴더가 볼트 밖이면 doctor가 판본에 맞는 정확한 `cd`/`Set-Location -LiteralPath`를 보여 줍니다. 공백·한글·따옴표를 인용하며 제어문자가 있는 경로는 자동 명령을 만들지 않습니다. 긴 줄표 `—version` 대신 ASCII 두 글자인 `--version`을 사용하세요.

Intel에서 Python 3.9만 있으면 `PYTHON_TOO_OLD`, 도우미는 `DEPENDENCY_FAILED`, 종합은 실패입니다. Python 3.10 이상을 공식 macOS 설치기로 직접 설치한 뒤 검수된 Intel 강의판 설치 명령을 다시 실행하세요. 일손 명령이 없는 상태에서 `ilson setup`을 안내하지 않습니다. 관리자 암호·기기 잠금 복구·로그인은 본인이 처리합니다.

## 일손/Python이 없는 경우와 고정 버전 한 줄

미리 받은 검수본 `tools/doctor.sh`를 `sh tools/doctor.sh --share`로, Windows는 `tools/doctor.ps1`을 PowerShell로 실행할 수 있습니다. 일손·Python·Node·계정·인터넷이 없어도 로컬 이력을 읽습니다.

강사는 검수된 **실제 커밋 SHA 40자리**와 해당 소스에서 아래 명령을 실행해 학생에게 줄 한 줄을 생성합니다. 생성기는 네트워크에 접속하지 않습니다. 출력은 Python 없이 시작하고, 다운로드 전에 run을 만들며, 완전히 받은 고정 소스의 SHA-256을 확인한 뒤 실행합니다.

```sh
python3 tools/build_install_commands.py --source-ref <검수된40자리SHA> --target intel-course
python3 tools/build_install_commands.py --source-ref <검수된40자리SHA> --target full-mac
python3 tools/build_install_commands.py --source-ref <검수된40자리SHA> --target windows-course
python3 tools/build_install_commands.py --source-ref <검수된40자리SHA> --target doctor-mac
python3 tools/build_install_commands.py --source-ref <검수된40자리SHA> --target doctor-windows
```

`doctor-*`의 출력이 일손 없는 학생용 독립 진단 한 줄입니다. 아직 공개되지 않은 SHA의 URL은 다운로드되지 않습니다. 배포 승인이 나기 전 이 예시를 공개 설치 명령으로 안내하지 마세요. 기존 `curl|sh`, `curl|bash`, `irm|iex`도 지원하지만 **첫 스크립트 바이트를 받기 전의 실패는 기록할 수 없습니다**. inline 시작 코드 자체의 붙여넣기 누락·파싱 실패도 그 안에서 기록할 수 없습니다.

종료 코드: 0=필수 단계 통과, 1=필수 실패/의존 생략, 2=사용법·잘못된 판본, 3=중단/진단·로그 불가, 4=확인 대기. PowerShell의 `iex`는 사용자의 열린 셸을 닫지 않고 화면의 `INSTALL_RESULT`와 상태 파일을 기준으로 합니다. 실제 파일 실행은 OS 종료 코드를 반환합니다. dry-run은 로그를 포함해 파일을 만들지 않습니다.

## 강의판 재설치 갱신과 복구

검수된 설치 명령 재실행은 허용된 helper 파일만 검사합니다. `install_payload.py`의 파일별 알려진 SHA-256과 같은 구판만 교체하고, 사용자 변경이 하나라도 있으면 파일 목록을 안내하고 쓰기 전에 중단합니다. 기존 볼트·CLAUDE.md·PATH 설정은 보존합니다. 알려진 형식의 Intel wrapper와 Windows Python 선택은 새 Python 경로로 갱신하고 이전본을 보관합니다. 알 수 없는 wrapper는 보존하고 실패를 알립니다.

코드 변경 전 `lib/.install-backups/upgrade-.../manifest.json`과 이전 코드를 남깁니다. 쓰기 실패는 이미 바꾼 코드만 자동 복구합니다. 검수본의 `course/install_payload.py`로 `python3 course/install_payload.py <설치된 lib> --rollback <upgrade-... 이름>`을 실행하면 manifest가 가리키는 이전 코드로 복구합니다. 갱신 이후 사용자가 바꾼 파일이 있으면 복구도 쓰기 전에 중단합니다. launcher 이전본은 Mac `.ilson-course/.launcher-backups/`, Windows `python-path.txt.before-diag-...`에 남으며 본인 경로를 검토해 직접 복구합니다.

전체판 배포는 기존 updater가 허용하는 `template/lib/*.py`, `*.sh`를 사용합니다. 설정·볼트·jobs.conf와 새 `tools/` 경로를 updater 허용 목록에 추가하지 않습니다. schema는 개발/검수 자료이며 설치 시작 시 다운로드하지 않습니다.

Windows 5.1 실기기 검증은 배포 전 별도 필요합니다. 이 구현의 Mac 검증 결과를 Windows 5.1 통과로 해석하지 않습니다.
