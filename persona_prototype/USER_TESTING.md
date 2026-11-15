# 직접 사용하기: Mock 웹 챗봇

## Codex Cloud의 현재 접속 상태

이 작업에서 Cloud 환경 상태를 조회했을 때 `connected/running`, 공유 Desktop
`enabled: true`로 확인됐다. Desktop의 실행 상태는 `unknown`이었다. 이 채팅에는
`open_cloud_preview`, `open_in_codex`, Desktop 브라우저 조작 도구가 제공되지 않아
사용자 PC용 포워딩 URL을 발급하거나 공유 Chrome 탭을 열 수 없었다.
이는 모든 Codex Cloud 제품에서 포워딩이 불가능하다는 뜻은 아니다. 현재 채팅에서
확인 가능한 범위와, 실제 발급된 미리보기 주소가 없다는 뜻이다.

지원되는 Codex 클라이언트에서 오른쪽 패널 **New tab (+) → Desktop**이 보이면
Desktop을 열고 **Take over**를 선택한 뒤 **그 안의 Chrome**에서
`http://127.0.0.1:8501`을 입력한다. 이 경로는 플랫폼의 Desktop 안내에 따른 것이며,
이번 작업에서는 공유 Desktop 연결을 직접 검증하지 못했다. 이 메뉴가 없으면 아래
로컬 실행 방법을 사용한다. Cloud 환경의 `127.0.0.1`은 사용자 PC 주소가 아니므로
PC Chrome 주소창에 그대로 입력해서 Cloud 앱에 접속할 수는 없다.

Cloud의 현재 프로세스는 Mock Backend 8000 / UI 8501,
기존 실제 모델 Backend 8001 / UI 8502이다. 이번 사용 검사는 **Mock 8501만** 사용했다.
새 실제 GPT-4o mini 호출은 하지 않았고 기존 원장 11회는 그대로다. Cloud 프로세스는
환경 종료/재시작 후 다시 시작해야 할 수 있다. Cloud 실행 명령은 [WEB_CHAT.md](WEB_CHAT.md)에 있다.

## PC 또는 VS Code에서 직접 실행

아래는 **Linux x86-64 또는 Windows WSL2 Ubuntu의 Bash** 기준이다.
Windows에서는 WSL2 Ubuntu와 VS Code의 WSL 확장을 설치하고 Ubuntu 터미널에서
실행한다. 네이티브 PowerShell/macOS 절차는 이번에 검증하지 않았다.
Git, 네트워크 연결, Hermes 활성화 스크립트가 설치하는 도구가 필요하다.
처음 활성화할 때 의존성 설치에 시간이 걸릴 수 있다.

```bash
git clone --branch feat/persona-gpt4o-mini-validation \
  https://github.com/hyeonjun-jin/hermes-agent.git
cd hermes-agent
# VS Code를 사용한다면 여기서 code . 실행 (WSL에서는 WSL 창으로 열림).
export HERMES_HOME="$HOME/.local/share/persona-chat-hermes"
export HERMES_RUNTIME_DIR="$HERMES_HOME/tools"
source ./activate
```

비공개 저장소라면 GitHub 계정의 저장소 읽기 권한이 필요하다. Clone이 거절되면
로컬 GitHub 로그인을 설정한다. 자격증명을 URL이나 소스에 쓰지 않는다.

첫 번째 VS Code 터미널(위 활성화를 수행한 터미널)에서 Backend를 실행한다.
프로토타입 DB/대화/피드백은 저장소 밖의 `--state`에 저장한다.

```bash
env -u PERSONA_API_KEY -u OPENAI_API_KEY \
  python -m persona_prototype.web_backend --dev --mode mock \
  --state "$HOME/.local/share/persona-chat-mock-state" --port 8000
```

두 번째 터미널에서 같은 저장소로 이동한 뒤 UI 전용 환경을 준비한다. 아래 uv 경로는
이 브랜치가 고정한 Linux x86-64 도구 위치다. UI 환경 생성·동기화는 최초 한 번만 필요하다.
Hermes의 관리 환경에 Streamlit을 직접 설치하지 않는다.

```bash
cd /path/to/hermes-agent
UV_BIN="$HOME/.local/share/persona-chat-hermes/tools/uv-0.13.5-linux-x64/uv"
UI_ENV="$HOME/.local/share/persona-chat-ui-venv"
"$UV_BIN" venv --python 3.13 "$UI_ENV"
"$UV_BIN" pip sync --python "$UI_ENV/bin/python" --require-hashes \
  persona_prototype/ui-requirements.lock
env -u PERSONA_API_KEY -u OPENAI_API_KEY \
  PERSONA_CHAT_API=http://127.0.0.1:8000 \
  "$UI_ENV/bin/streamlit" run persona_prototype/ui.py \
  --server.address 127.0.0.1 --server.port 8501 --server.headless true \
  --browser.gatherUsageStats false
```

`/path/to/hermes-agent`는 실제 Clone 경로로 바꾼다. 이제 **사용자 PC의 브라우저**에서
**http://localhost:8501**을 연다. 이 주소는 앱을 PC/WSL에서 실행했기 때문에 사용할 수
있으며 Cloud 환경 포워딩 주소가 아니다. WSL2의 일반적인 localhost 전달을 사용한다.
WSL 네트워크 설정에 따라 연결되지 않으면 VS Code WSL 창의 **Ports → Forward a Port →
8501 → Open in Browser**를 사용하고 표시된 **Forwarded Address**를 연다. 이것은 로컬
WSL 연결에 대한 절차이며 Codex Cloud로의 VS Code 원격 연결을 제공하는 기능이 아니다.
UI만 브라우저에 접근하면 된다. 8000은 UI 서버가 사용하는 내부 Backend 주소다.

Mock에는 OpenAI 키가 필요 없다. FastAPI/uvicorn 등 Backend 의존성은 Hermes의 PM
환경을 사용한다. UI는 Python 3.13, Streamlit 1.67.0, HTTPX 0.28.1과 해시 고정된
전이 의존성을 사용한다. 선택적인 자동 브라우저 검사는 별도로 Playwright와 Chromium이
필요하지만, 사용자가 브라우저로 대화하는 데에는 필요 없다.

## 화면에서 테스트하는 순서

1. **현재 Mock 모드입니다** 배너를 확인하고 Alice를 선택한 뒤 **새 대화**를 누른다.
2. `제 업무 코드는 R-42입니다. 기억해주세요.`를 입력한다.
3. 같은 대화에서 `앞서 알려준 코드는 무엇인가요?`를 입력하고 R-42 답변을 확인한다.
4. Bob을 선택해 새 대화에서 `프로젝트를 알려주세요.`를 입력한다.
   beacon과 표 형식, Alice 기록과 분리된 대화를 확인한다.
5. Carol을 선택해 새 대화에서 `현재 프로젝트 계획을 조사 분석 검증해 주세요.`를 입력한다.
   cedar와 `doc-5`, **활용한 기억과 검토 내역**의 세 역할 실행 및 근거를 확인한다.
6. 답변의 **답변 피드백**을 열어 평가·의견을 입력하고 저장 완료 표시를 확인한다.
7. Alice로 돌아가 R-42 대화가 남아 있는지 확인한다. 새로고침 후 대화 기록에서 다시 연다.

자동 Mock Chromium 검사는 위 흐름을 실행한다. Backend/UI가 실행 중일 때:

```bash
python3 tests/browser/persona_chat_smoke.py
```

## 한계

- Mock은 지정된 시나리오의 결정적 응답이다. 임의 질문의 이해나 모델 추론 품질을
  평가하는 용도가 아니다. 세 역할과 도구는 실제 Hermes 경로를 거쳐 실행한다.
- 사용자 선택과 대화 재개는 개발용이다. 운영 인증·적대적 다중 사용자 보안은 제공하지 않는다.
- 대화는 최대 20턴이며, 재개 시 세션 토큰이 회전해 예전 탭은 접근이 거절될 수 있다.
- 단일 Backend/worker만 지원한다. 상태 DB 암호화·보존 정책·요청 중복 방지는 미구현이다.
- 문서 ID는 Mock 문서 식별자이며 외부 원문 링크/문서 뷰어는 없다.
- 일부 응답은 로컬 형식 보정을 사용한다. 자동 출처/언어 검사는 의미 정확성을 보증하지 않는다.
- 기본 피드백은 저장만 한다. 동의한 선호는 [제한된 Alignment 기능](ALIGNMENT.md)으로
  Mock 검증 후 별도 승인할 수 있다. LLM TextGrad와 자동 적용은 구현하지 않았다.
- 이 로컬 가이드는 Mock 모드 대상이다. Codespaces의 실제 모델 Backend 실행은
  [CODESPACES.md](CODESPACES.md)를 따른다. Codex 정책 파일을 만들어 우회하지 않는다.
