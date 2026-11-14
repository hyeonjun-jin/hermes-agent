# Hermes + Persona prototype

The FastAPI + Streamlit conversational prototype, persistent sessions, development
user selection and cost-limited real model instructions are in [WEB_CHAT.md](WEB_CHAT.md).
For Cloud access limitations, local PC/VS Code setup and hands-on Mock checks,
see [USER_TESTING.md](USER_TESTING.md).
For explicit real GPT-4o mini mode with Codespaces Secrets and private port
forwarding, see [CODESPACES.md](CODESPACES.md).

For the repaired automatic-memory flow, tag provenance, output-format auditing
and latest live controlled experiment, see [PERSONALIZATION_FIXES.md](PERSONALIZATION_FIXES.md).
For native Hermes Research/Analysis/Verification delegation, boundaries, budgets
and actual live results, see [MULTI_AGENT.md](MULTI_AGENT.md).

This standalone prototype uses the existing `AIAgent.run_conversation` loop and
the public `MemoryManager` injection parameter. `PersonaMemoryProvider` implements
the actual Hermes `MemoryProvider` ABC. The initialized manager supplies its static
persona, tools, and completed-turn synchronization to Hermes. No core files or
dependency manifests are modified; no new bundled memory provider is installed.

## Run

From the existing checkout (do not create a worktree):

```bash
cd /workspace/hermes-agent
export HERMES_HOME=/workspace/hermes-dev-data
export HERMES_RUNTIME_DIR=/workspace/hermes-dev-data/tools
export XDG_CACHE_HOME=/workspace/.cache
export XDG_DATA_HOME=/workspace/.local/share
export UV_PYTHON_INSTALL_DIR=/workspace/.local/share/uv/python
source ./activate
python -m persona_prototype.app --mode mock
```

The CLI runs the same question for all three users and prints each persona,
answer, and tool arguments/results. Use `--user bob`, `--question '프로젝트 계획'`,
or `--root $TMPDIR/my-persona-demo` to select an identity/question/independent store.
The CLI's selected identity is a trusted fixture, **not authentication**. The app
boundary accepts a `Principal`; a future server must build it from authenticated
credentials, never from an untrusted request body.

State persists under `--root`: SQLite memory and per-user Hermes homes. Every
`chat` call starts a new session with a fixed persona snapshot. Completed system
answers are stored as **unconfirmed** episodes, never as ground-truth preferences.
The fixture initializer is idempotent and seeds only empty semantic profiles.

### Real LLM

Set `PERSONA_BASE_URL`, `PERSONA_MODEL`, and `PERSONA_API_KEY` securely in the process
environment, then run:

```bash
python -m persona_prototype.app --mode real --user alice
```

Requires an OpenAI-compatible Chat Completions endpoint with tool calling.
This path uses the same loop, memory and tools; no real provider invocation was
performed in this prototype's validation. Live calls incur provider costs and
send synthetic fixture context to that provider. Keys are not saved in state or
printed. There are no new Python dependencies.

For a fresh-state three-user comparison with machine-readable evidence, run:

```bash
python -m persona_prototype.validation --output $TMPDIR/persona-live-validation.json
```

Missing settings produce exit code 2 and a blocked report without making model
calls. See [VALIDATION.md](VALIDATION.md) for current live-validation status,
secure configuration, hardcoded-vs-model attribution, failure coverage and the
recommended future separation of business tools from MemoryProvider. Tool traces
now include successful, empty, denied, invalid and unavailable-backend outcomes.

## Tests

### Cost-limited OpenAI gpt-4o-mini validation

The published runtime already supplies `PERSONA_BASE_URL=https://api.openai.com/v1`
and `PERSONA_MODEL=gpt-4o-mini`. The key is read only from `PERSONA_API_KEY` at
runtime; it is never copied into code or a report. Allow `api.openai.com` in the
running environment's outbound network settings before executing:

```bash
python -m persona_prototype.mini_validation --output $TMPDIR/gpt-4o-mini-validation.json
```

This dedicated runner requires the exact OpenAI endpoint/model, checks the local
cloud network-policy snapshot and fails closed on missing settings, blocked access
or unknown policy. Restart/update the environment if its startup policy snapshot
does not yet reflect a network-settings change. The earlier general `validation`
runner remains available, but does not provide these hard remote-call limits.

Each user receives a fresh session using the original fixtures. A localhost
gateway forwards only Chat Completions, buffers the response, and translates it
to Hermes' expected streaming format when necessary. It forces `gpt-4o-mini`,
caps output at 512 tokens, and admits at most 4 upstream attempts per user (12
total). Requests above 64,000 serialized bytes are rejected before forwarding.
HTTPX does not automatically retry; the first upstream error latches the gateway
closed and stops subsequent users. Fresh Hermes profile configuration selects
one API attempt and no post-exhaustion auto recovery; loop iterations are 4 with
a 60-second run budget. The gateway still blocks extra remote requests if Hermes
tries a grace/auxiliary call. Existing profile configuration is never overwritten.

Reports include actual upstream attempts (including failures), per-call reported
usage, totals and estimated USD cost. Missing response usage produces a null cost,
not a fabricated zero. Pricing uses provisional $0.15 input / $0.60 output per
million tokens, charging cached input at full rate; confirm current OpenAI pricing
before interpreting the estimate as a bill. No paid compatibility probe runs
separately: a successful model-generated tool call in the main run is evidence of
compatibility. Offline fixtures do not establish live model availability.

Current run: endpoint/model variables match, key variable is present (validity
untested), but `api.openai.com` is absent from the enforced network policy. No
external request was attempted: 0 calls, 0 tokens, $0. Alice/Bob/Carol live
personalization and live Tool Calling remain untested.

After activation:

```bash
scripts/run_tests.sh -j 1 tests/persona_prototype/test_personalization.py -q
```

Run all prototype tests, including the live-runner's offline exception tests:

```bash
scripts/run_tests.sh -j 2 tests/persona_prototype/ -q
```

The repository runner writes `/var$TMPDIR/hermes-pytest-1000`. In the cloud command
sandbox, an approved escalated test invocation may be required for this path.
Optional Chromium's blocked download does not affect these tests.

Six behavioral tests exercise real Hermes HTTP model calls and provider tool
dispatch, per-user search tags/environment arguments/output formats, changed
episodic focus, semantic updates in a new session, saved completed turns,
cross-user and missing-scope denial, unknown tool arguments, persistence,
idempotent seed, child write suppression and concurrent memory access.

The mock model is a deterministic HTTP fixture (including streaming support),
not an intelligent model or evidence of LLM quality. It reads persona JSON and
confirmed tool-returned episodes and emits tool calls. Its fixed planning policy
does not test arbitrary natural-language reasoning. Real-model quality evaluation
remains separate.

## Data and boundaries

* 3 fictional users, 6 shared fictional documents, 5 episodes per user, 3 project
  environments; no POSCO or other actual enterprise data.
* Semantic memory is explicit structured preference data. `build_persona` allows
  known output formats; automatic semantic extraction is not implemented.
* Episodic search is a deterministic lexical overlap baseline with recency ties
  and top-K, **not vector similarity**. No-match returns no episodes.
* `OwnerOnly` checks exact owner and explicit scopes on every memory operation.
  Environment access additionally checks the user's project. Mock documents are
  shared but require `documents:read`; real row/document ACLs belong in the backend.
* Tool schemas contain no user ID. The provider binds a principal outside the LLM,
  rejects extra arguments, and records successful tool calls for inspection.
* Mock RAG and Environment are provider-owned tools through
  `get_tool_schemas`/`handle_tool_call`; they are **not separately installed general
  Tool Plugins**. `EnterpriseData` can replace their data backend without changing
  the loop. Direct calls and ordinary Hermes applications do not auto-discover this
  prototype: use the supplied application entry point.

## Extension contracts (not implemented features)

`domain.py` defines `EnterpriseData`, `Authorizer`, `Specialist` and
`PreferenceAlignment`. Native specialist implementation is in `multi_agent.py`;
the standalone `Specialist` protocol is not an alternate inference engine.
No alignment worker, feedback UI, FastAPI server, web UI, vector index,
enterprise API, production identity provider, encryption/retention policy or
end-to-end multi-agent budget enforcement is implemented. `ChatApplication.chat`
is a synchronous service boundary for a future API; it is not an HTTP backend.
Before production, separate blocking calls from the async server event loop and
validate tenant ACLs and concurrent full-agent execution. Concurrent SQLite
isolation tests do not establish full-agent thread safety.
