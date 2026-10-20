Intel MacBook용 일손 설치 묶음 — 2026-10-16

대상: Intel 64비트 Mac, macOS13 이상. 사진의 2020년 13형 MacBook Pro/i5/16GB는 이 범주에 해당한다.
이 묶음은 Intel 허용 조건과 설치 흐름을 모의 검증한 준비본이다. 해당 실제 Intel 맥북에서 설치/실검색은 아직 하지 않았다.

사용 방법
1. ilson-intel-mac-20261016.zip을 대상 맥북에 복사하고 압축을 푼다. AirDrop 또는 USB로 전달해도 된다.
2. 터미널을 열어 아래처럼 bash와 공백을 입력하고, 압축을 푼 폴더의 install-intel.command 파일을 터미널로 끌어온 뒤 Return:
   bash [끌어온 파일 경로]
   또는 install-intel.command를 더블클릭한다. macOS가 열기를 막으면 전역 보안 설정을 해제하지 말고 터미널의 bash 방식으로 실행한다.
3. Homebrew/개발 도구 설치에 필요한 관리자 비밀번호 및 설치 화면은 이 맥북에서 직접 처리한다.
4. 설치 후 claude 또는 codex를 실행해 본인 계정으로 로그인한다. 계정·구독·사용량은 새 기기에서 확인한다.
5. ~/.local/bin/ilson open으로 관리자를 연다. 리서치에서 간단한 질문을 먼저 실행한다.
   기본 Claude 유지 / Codex로 변경: ~/.local/bin/ilson llm codex
   되돌리기: ~/.local/bin/ilson llm claude

포함: Box2026.10.16.3, research0.16.1. 기본 LLM에 따라 검색 연동, 공식 원문 우선, 주장별 출처, 미확인/충돌 표시.
이 설치기는 새 기기용이다. 기존 ~/.ilson-cli 또는 ~/ilson이 있으면 임의 덮어쓰지 않는다. 같은 묶음으로 시작한 미완료 설치는 재실행 가능하다.
원본·인증·개인 자료는 묶음에 포함하지 않았다. 필요한 CLI/앱은 공식 배포에서 대상 CPU에 맞춰 다운로드한다. 인터넷 연결이 필요하다.
노트북의 잠자기·화면잠금·FileVault를 바꾸지 않고 예약업무도 시작하지 않는다. --configure-machine이나 ilson start는 수업 설치에 필요 없다.
처음 설치할 때 Tailscale 연결은 필요 없다(일손 릴리스를 묶음에 포함). 이후 ilson update의 현재 배포 서버 접근에는 승인된 Tailscale 연결이 필요하다.
Homebrew는 현재 Intel을 Tier3로 분류한다. 일부 의존 도구에서 설치 실패 또는 소스 빌드가 발생할 수 있다. 실패를 무시하거나 CPU 검사를 우회하지 말고, 마지막 오류를 확인한다.
영상 렌더·브라우저 자동화·카카오톡 연동은 이 기본 설치의 실기 검증 범위가 아니다. 수업에서 필요한 기능부터 따로 연결한다.

공식 근거(2026-10-16 확인)
Claude Code: https://code.claude.com/docs/en/setup (macOS13+, x64/ARM64)
Codex CLI: https://github.com/openai/codex/blob/main/README.md (x86_64-apple-darwin)
Homebrew: https://docs.brew.sh/Installation 및 https://docs.brew.sh/Support-Tiers

설치 전 묶음 확인만: bash [install-intel.command 경로] --check

검증 후 읽기 전용 점검: ~/.local/bin/ilson doctor
로그인/선택 기능 미연결 경고는 항목별로 확인한다. 설치 성공과 실제 검색 성공은 별도다.
