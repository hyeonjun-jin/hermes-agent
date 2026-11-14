# Hermes + Persona prototype

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
or `--root /tmp/my-persona-demo` to select an identity/question/independent store.
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
python -m persona_prototype.validation --output /tmp/persona-live-validation.json
```

Missing settings produce exit code 2 and a blocked report without making model
calls. See [VALIDATION.md](VALIDATION.md) for current live-validation status,
secure configuration, hardcoded-vs-model attribution, failure coverage and the
recommended future separation of business tools from MemoryProvider. Tool traces
now include successful, empty, denied, invalid and unavailable-backend outcomes.

## Tests

After activation:

```bash
scripts/run_tests.sh -j 1 tests/persona_prototype/test_personalization.py -q
```

Run all prototype tests, including the live-runner's offline exception tests:

```bash
scripts/run_tests.sh -j 2 tests/persona_prototype/ -q
```

The repository runner writes `/var/tmp/hermes-pytest-1000`. In the cloud command
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

`domain.py` defines `EnterpriseData`, `Authorizer`, `Specialist` (research,
analysis, verification) and `PreferenceAlignment`. They are contracts only.
No subagents, alignment worker, feedback UI, FastAPI server, web UI, vector index,
enterprise API, production identity provider, encryption/retention policy or
end-to-end multi-agent budget enforcement is implemented. `ChatApplication.chat`
is a synchronous service boundary for a future API; it is not an HTTP backend.
Before production, separate blocking calls from the async server event loop and
validate tenant ACLs and concurrent full-agent execution. Concurrent SQLite
isolation tests do not establish full-agent thread safety.
