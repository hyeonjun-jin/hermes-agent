# Codespaces에서 GPT-4o mini 웹 챗봇 실행

`feat/persona-gpt4o-mini-validation` 브랜치의 웹 Backend용 안내다.
기존 `mini_validation`/`multi_validation` CLI는 Codex 정책 전용 검사를 그대로 사용한다.
이번 변경과 테스트에서는 유료 API를 호출하지 않았다. 아래 `--mode real` Backend에서
메시지를 보내면 실제 API 비용이 발생한다. 시작 및 `/health` 조회는 API를 호출하지 않는다.

## Secrets와 네트워크

GitHub Settings → Codespaces → Secrets에서 **PERSONA_API_KEY**를 만들고 이 저장소에
접근을 허용한다. 조직 Secrets를 쓰는 경우 해당 조직의 Codespaces 설정을 사용한다.
기존 Codespace는 재시작하여 Secret을 환경변수로 전달받는다. 값을 파일·명령어·스크린샷에
복사하지 않는다. 아래 명령은 값이 아닌 존재 여부만 확인한다.

```bash
python3 -c 'import os; assert os.environ.get("PERSONA_API_KEY", "").strip(), "PERSONA_API_KEY missing"; print("PERSONA_API_KEY: configured")'
```

Backend는 `CODESPACES=true`와 비어 있지 않은 `CODESPACE_NAME`으로 Codespaces를
인식한다. Codex 정책 파일이 존재하면 그 검사가 항상 우선하며, 거부·손상·읽기 오류에
대해 Codespaces로 우회하지 않는다. Codex 디렉터리가 있는데 정책만 누락돼도 중단한다.
Codex 흔적이 없고 Codespaces 환경변수가 모두 설정된 경우에만 정책 파일 없이 시작한다.
알 수 없는 환경은 중단하며 수동 `skip-policy` 옵션은 없다.

Codespaces에는 Codex 정책 파일을 만들지 않는다. `api.openai.com:443`으로 HTTPS
통신하며 플랫폼/조직의 실제 egress 제한, DNS, 환경 프록시와 인증서 설정을 따른다.
TLS 검증은 켜져 있고 HTTP 리다이렉트는 따라가지 않는다. 플랫폼 환경변수는 인증이나
네트워크 허용 증명이 아니며, 플랫폼 방화벽이 최종적으로 전송을 통제한다. 조직 정책상
차단이면 관리자에게 허용을 요청한다. 앱에서 터널·다른 엔드포인트로 재전송하지 않는다.
실제 Codespaces에서의 OpenAI 도달 가능성/Secret 유효성은 이번 오프라인 테스트로
검증하지 않았다.

## Backend: 첫 번째 Codespaces 터미널

이미 Mock을 실행한 저장소와 Hermes 환경을 재사용한다. 아래 `/workspaces/hermes-agent`는
Codespaces 기본 Clone 위치다. 다른 경로에 Clone했다면 해당 경로로 바꾼다.

```bash
cd /workspaces/hermes-agent
git switch feat/persona-gpt4o-mini-validation
git pull --ff-only origin feat/persona-gpt4o-mini-validation

# Mock에 사용한 HERMES_HOME/HERMES_RUNTIME_DIR이 있다면 그대로 유지한다.
# 설정하지 않았을 때만 저장소 밖의 개발 환경 경로를 사용한다.
export HERMES_HOME="${HERMES_HOME:-$HOME/.local/share/persona-chat-hermes}"
export HERMES_RUNTIME_DIR="${HERMES_RUNTIME_DIR:-$HERMES_HOME/tools}"
source ./activate
export PERSONA_BASE_URL=https://api.openai.com/v1
export PERSONA_MODEL=gpt-4o-mini
python -c 'import os; assert os.environ.get("PERSONA_API_KEY", "").strip(), "PERSONA_API_KEY missing"; print("PERSONA_API_KEY: configured")'

python -m persona_prototype.web_backend --dev --mode real \
  --state "$HOME/.local/share/persona-chat-codespaces-real" --port 8001
```

Mock과는 상태 디렉터리를 구분한다. 이 real 디렉터리를 계속 재사용해야 재시작 후에도
12회 예산이 유지된다. 예산을 초기화하려고 `usage.json`을 지우거나 다른 디렉터리를
지정하지 않는다. 기존 Cloud 원장은 Codespaces로 자동 이전되지 않으므로 이 경로의
첫 실행은 별도 Codespaces 테스트 예산을 만든다. Backend는 단일 프로세스로만 실행한다.

## Streamlit: 두 번째 Codespaces 터미널

기존 Mock UI와 별도로 8502를 사용하고 실제 Backend 8001에 연결한다.
아래 UI 가상환경 경로가 이미 Mock에서 만든 경로와 다르면 해당 경로로 바꾼다.
UI 환경이 없는 경우에만 다음 초기화를 실행한다 (Linux x86-64 기준).

```bash
cd /workspaces/hermes-agent
export HERMES_HOME="${HERMES_HOME:-$HOME/.local/share/persona-chat-hermes}"
export HERMES_RUNTIME_DIR="${HERMES_RUNTIME_DIR:-$HERMES_HOME/tools}"
UV_BIN="$HERMES_RUNTIME_DIR/uv-0.13.5-linux-x64/uv"
UI_ENV="$HOME/.local/share/persona-chat-ui-venv"
# UI_ENV가 아직 없을 때만:
"$UV_BIN" venv --python 3.13 "$UI_ENV"
"$UV_BIN" pip sync --python "$UI_ENV/bin/python" --require-hashes \
  persona_prototype/ui-requirements.lock
```

이후 UI 실행 명령:

```bash
env -u PERSONA_API_KEY -u OPENAI_API_KEY \
  PERSONA_CHAT_API=http://127.0.0.1:8001 \
  "$HOME/.local/share/persona-chat-ui-venv/bin/streamlit" run persona_prototype/ui.py \
  --server.address 127.0.0.1 --server.port 8502 --server.headless true \
  --browser.gatherUsageStats false
```

Codespaces의 **Ports** 탭에서 **8502**를 추가하고 Visibility를 **Private**로 유지한 뒤
**Open in Browser**를 누른다. GitHub 로그인된 브라우저에서 표시된 Forwarded Address를
사용한다. 일반적으로 `https://<codespace-name>-8502.app.github.dev` 형태지만 실제 주소는
Ports 탭에서 확인한다. Backend 8001은 UI 서버만 사용하므로 포워딩할 필요가 없다.
개발용 사용자 선택은 인증이 아니므로 UI 포트를 Public으로 바꾸지 않는다.

## 비용 제한과 확인 방법

- 기본값은 계속 Mock이며, real은 명시적인 `--mode real`에서만 활성화된다.
- API 키는 Backend의 `PERSONA_API_KEY` 환경변수에서만 읽는다. UI로 전달하지 않는다.
- 모든 사용자·역할이 `--state`의 **12회 전송 상한**을 공유한다. 응답당 최대 512토큰이다.
- 자동 외부 재시도는 0회다. 첫 API/연결 오류 후 예산을 닫고 추가 전송하지 않는다.
- 토큰/비용은 UI와 Backend `/health`, `usage.json`에서 확인한다. 사용량이 반환되지 않은
  실패는 비용을 0으로 간주하지 않고 미확인으로 기록한다. HTTPS 클라이언트는 플랫폼
  프록시를 사용하지만, 프록시 내부 재시도 동작까지 앱이 통제하는 것은 아니다.
- 복잡한 전체 워크플로는 시작 전 8회분이 남아 있어야 한다.

메시지를 보내지 않고 설정과 남은 예산만 확인하려면:

```bash
curl --fail http://127.0.0.1:8001/health
```

Mock은 기존처럼 `--mode mock`, Backend 8000과 UI 8501을 사용한다.
기존 [Mock 테스트 안내](USER_TESTING.md)와 [웹 구조/한계](WEB_CHAT.md)를 참고한다.
