# Persona Chat: development web prototype

FastAPI + Streamlit over the existing Hermes AIAgent, scoped MemoryProvider and
native `delegate_task` specialists. No Hermes core or root dependency lock changes.
The earlier Multi-Agent implementation was committed/pushed as `95c09ba665` on
`feat/persona-gpt4o-mini-validation` before this web work began. Main was not merged.

## Start the backend

Use the existing checkout and its PM environment:

```bash
cd /workspace/hermes-agent
export HERMES_HOME=/workspace/hermes-dev-data
export HERMES_RUNTIME_DIR=/workspace/hermes-dev-data/tools
export XDG_CACHE_HOME=/workspace/.cache
export XDG_DATA_HOME=/workspace/.local/share
export UV_PYTHON_INSTALL_DIR=/workspace/.local/share/uv/python
source ./activate
python -m persona_prototype.web_backend --dev --mode mock \
  --state /workspace/persona-web-mock-state --port 8000
```

For real GPT-4o mini, use **explicit** `--mode real`, port 8001 and a separate
`--state /workspace/persona-web-real-state`. Supply `PERSONA_BASE_URL` as
`https://api.openai.com/v1`, `PERSONA_MODEL` as `gpt-4o-mini`, and
`PERSONA_API_KEY` through secure runtime environment settings. Allow `api.openai.com`
in network settings. On Codex the existing policy check is retained; recognized
GitHub Codespaces without a Codex installation uses platform-enforced HTTPS egress.
See [CODESPACES.md](CODESPACES.md) for Secrets and private port-forwarding commands.
Real mode refuses missing settings or a denied/invalid Codex policy;
there is no automatic Mock fallback. Keys never go in UI requests or reports.

The backend binds only 127.0.0.1, uses one process, and serializes embedded Hermes
inference to avoid concurrent process-global runtime interference. Do not launch
multiple backends/workers against the same state directory.

## Start Streamlit

The UI has an independent environment, so installing Streamlit does not mutate
Hermes' PM-managed dependencies. In this cloud machine Python 3.13 and Chromium
are available. For another machine install the matching interpreter first.

```bash
cd /workspace/hermes-agent
export UV_CACHE_DIR=/workspace/.cache/uv
UV_BIN=/workspace/hermes-dev-data/tools/uv-0.13.5-linux-x64/uv
# Run venv creation only when the UI environment does not already exist.
"$UV_BIN" venv --python /usr/bin/python3 /workspace/persona-ui-venv
"$UV_BIN" pip sync --python /workspace/persona-ui-venv/bin/python \
  --require-hashes persona_prototype/ui-requirements.lock
env -u PERSONA_API_KEY -u OPENAI_API_KEY \
  PERSONA_CHAT_API=http://127.0.0.1:8000 XDG_CACHE_HOME=/workspace/.cache \
  /workspace/persona-ui-venv/bin/streamlit run persona_prototype/ui.py \
  --server.address 127.0.0.1 --server.port 8501 --server.headless true \
  --browser.gatherUsageStats false
```

Open `http://127.0.0.1:8501` in the **cloud environment's browser**. For the real
backend set `PERSONA_CHAT_API=http://127.0.0.1:8001` and use UI port 8502. These
loopback addresses are not public sites; accessing them from a local computer
requires the platform's connection/port-forwarding support.

The sidebar selects Alice/Bob/Carol, creates or resumes conversations and displays
the frozen Persona and conversation history. The chat view shows answers, source
IDs, recall/role traces, separate quality/format audits and feedback. Feedback is
stored for inspection only; it never runs Test-Time Alignment or modifies Persona.

## Sessions and development identity

The old one-shot `ChatApplication.chat()` generated a new session each request.
It now optionally accepts a stable session ID, complete prior Hermes messages and
a frozen Persona. The web service stores these in SQLite and passes them back on
each turn, while rebuilding/closing the runtime agent to bound resources. This
maintains conversation context without implementing another agent loop. Each
conversation's system/persona and tool schemas stay fixed; tool-choice controls
are per turn. Prior-turn tool results cannot accidentally disable tools on a new
turn. Retrieved source IDs remain attributable on follow-up questions.

SQLite preserves sessions, raw model history, rendered answers and feedback over
backend restarts. Browser reload resumes the selected development user's stored
conversation. A development resume rotates a random session token, invalidating
older tabs using that credential. Tokens are hashed in storage; every ordinary
history/message/feedback route checks the token against the conversation owner.
Tests cover cross-user/token rejection. A session is capped at 20 turns; create a
new conversation when reached. No silent history truncation is performed.

**The development selector/resume endpoints are not authentication.** They exist
only behind explicit `--dev` and a loopback listener; anyone authorized to access
this development app can choose a fixture user. Without `--dev` they return 403.
Production authentication, tenant provisioning, encryption/retention policies,
request idempotency, multi-worker coordination and hostile multi-tenant operation
are not implemented. Do not expose this prototype publicly or use confidential data.

## Costs

Real mode shares a hard **12 upstream-call cap** across all users, turns and native
children. Each call requests at most 512 output tokens. No HTTP retry or automatic
provider fallback is used. A role cap/upstream error closes the budget. A complex
workflow needs eight available calls before starting, preventing a partial paid
workflow when only a few credits remain. Usage is reserved on disk before sending,
then completed with returned token counts. Restarting the backend does not reset
`usage.json`; unknown usage stays unknown rather than being reported as free.

The cap is attached to a state directory. Allocate a different state directory
only when intentionally authorizing a new budget; no UI button silently resets it.
The current live verification used 11 calls and leaves one simple call available.
Use Mock mode for unlimited development conversations without API spend. The
remaining credit cannot run an eight-call complex workflow and will be rejected
before inference. Estimates use the existing provisional $0.15 input / $0.60 output
per million tokens, charging cached input at full rate. Check current prices for billing.

## Tests and observed results

```bash
# In the activated Hermes environment:
scripts/run_tests.sh -j 2 tests/persona_prototype/ -q
scripts/run_tests.sh -j 2 tests/agent/test_memory_provider.py \
  tests/agent/test_memory_provider_init.py tests/tools/test_delegate_toolset_scope.py \
  tests/ci/test_prompt_surface.py -q
# Optional Chromium browser smoke, with MOCK backend 8000 and UI 8501 running:
python3 tests/browser/persona_chat_smoke.py
```

Final verification: 38 prototype tests plus 83 selected Hermes regression tests
passed (121 total). `python scripts/check --base HEAD` passed all 19 checks.
The full Hermes test suite was not run. Shell examples use the activated Hermes
environment's `$TMPDIR` for scratch output.

The optional browser smoke requires Python Playwright and `/usr/bin/chromium`;
it first checks the Mock banner before sending messages. It verified actual UI
typing, user changes, two-turn recall of R-42, isolated histories, Carol's native
three-role flow and citations, feedback submission and browser reload. Browser
tests are not a claim of model intelligence. UI dependencies have a hash-pinned lock.

Live verification used the real FastAPI endpoints, same session for Alice's two
turns, and the original fixture data:

| Case | Calls | Observed result |
|---|---:|---|
| Alice complex | 8 | Research/Analysis/Verification completed; Korean output, doc-1/doc-2, confirmed Environment separated from document-search gaps |
| Alice follow-up | 1 | Same session recalled atlas/small-unit deployment without new tool calls or children |
| Bob Persona | 1 | beacon/table preference; raw Korean answer locally rendered as a table |
| Carol Persona | 1 | cedar/explanation preference; Korean response without child delegation |

Total: **11 actual calls**, 53,281 input / 1,139 output tokens, estimated
**$0.00867555**, all HTTP 200. No external retries and no extra paid browser call.
The real UI also displayed these stored responses, source IDs and follow-up in
<!-- no-tmp: ok — exact path of the already completed live experiment artifact -->
Chromium. Full report: `/tmp/persona-web-real-validation.json`. Usage remains in
the real state's `usage.json`, not Git. Final raw language and semantic observations
are distinct from local format conversion; format fallback still applied for Alice
and Bob. The rule-based quality audit detects only limited observable issues and
never proves semantic correctness. Human review of this one fixture experiment
confirmed the main Environment/document distinction; general corpora and repeated
runs remain unvalidated.

To repeat the full live experiment with an explicitly allocated **fresh** backend
budget (this command refuses a partially consumed budget):

```bash
python -m persona_prototype.web_validation --api http://127.0.0.1:8001 \
  --output "$TMPDIR/persona-web-real-validation.json"
```

No web UI conversation automatically retrains a model, optimizes a Persona or
performs Test-Time User Preference Alignment.
