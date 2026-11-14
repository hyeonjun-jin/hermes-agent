# Validation status and review notes

## Current outcome

Live personalization is **not validated**. The running machine has none of
`PERSONA_BASE_URL`, `PERSONA_MODEL`, `PERSONA_API_KEY`; standard OpenAI and Anthropic
key variables were also absent. Values were never printed. The real-mode runner
was executed and returned `blocked_configuration` with an empty user-results list;
no external LLM request was made. A blocked report is not a successful comparison.

## Configure and rerun

In the cloud environment's secure settings, inject:

* `PERSONA_BASE_URL`: your authorized OpenAI-compatible endpoint including `/v1`.
* `PERSONA_MODEL`: the actual tool-calling model/deployment identifier.
* `PERSONA_API_KEY`: its credential; never put it in source, Git, or chat.

Ensure outbound network settings permit that endpoint. Remote endpoints require
HTTPS; embedded credentials and URL query secrets are rejected. Start a shell with
the updated bindings, activate the environment as described in README, then run:

```bash
python -m persona_prototype.validation --output /tmp/persona-live-validation.json
```

Exit codes: `2` missing/invalid settings (no model call), `1` execution failure,
`0` all three loops returned without a reported loop error. **Exit 0 is not a
personalization-quality pass**. Inspect the JSON's per-user persona, selected calls,
arguments, actual recalled episodes, environment results and final answer.
`quality_verdict` intentionally remains `not_evaluated`: no automatic LLM judge is
implemented. Run identifiers use fresh session IDs and a fresh temporary fixture
store, leaving previous demo memories untouched. The temporary store is removed
after the run; the JSON preserves the retrieved evidence. Don't commit live logs
without reviewing their contents. The runner does not save the endpoint or key.

## What is hardcoded and what the real model decides

* Fixture identities, projects, formats and confirmed focus preferences are
  explicit input data. Persona Builder deterministically maps allowed preferences;
  it is not a learned profile extractor.
* The shared system prompt asks for recall and suggests using historical focus
  for search. Thus the experiment measures preference-conditioned tool use under
  common instructions, not spontaneous discovery of an unconstrained tool policy.
* In real mode there is no Alice/Bob/Carol branch selecting tool calls or writing
  final answers. The external model generates names, arguments and response text.
  Retrieval filtering and access denial are deterministic backend enforcement.
* `mock_llm.py` does branch on format and memory focus. Offline results from this
  fixture prove plumbing, not real-model reasoning or personalization quality.
* Seeing an environment tool result proves retrieval, not use. Compare the final
  answer against its project/stage/constraint. Likewise, different text alone does
  not prove meaningful personalization: compare tools, arguments and evidence.

Review live results for each user: relevant memory retrieved; focus reflected in
search without changing facts; permitted project queried; environment constraints
reflected; appropriate format; document citations grounded. Mark missing calls,
empty search and errors explicitly. Repeat live runs before drawing general
quality conclusions. No actual provider rate-limit/authentication failures or
live-model recovery have been exercised in this session.

## Exceptions tested offline

Tests cover missing settings with a guard that fails if a model is called;
credential-bearing/invalid endpoint URLs; invalid/unknown tool arguments; memory
isolation and scope denial; cross-project denial; empty retrieval; simulated
backend timeout with sanitized error; persisted failure traces; and a scripted
HTTP model making denied/empty tool calls through the actual Hermes loop.
Backend-timeout and argument-validation checks are direct provider tests;
the denied/empty-call test exercises the full loop. These are not live-model
exception or recovery tests.

## MemoryProvider vs general Tool Plugin

Keeping recall and completed-turn synchronization in MemoryProvider is appropriate.
Embedding RAG and Environment tools there is adequate for this minimal prototype,
but couples enterprise connectivity to memory activation: disabling the memory
toolset also hides business tools; selecting a different memory provider replaces
them; specialist agents may skip memory providers by default.

For a larger system, move document/environment schemas and handlers into a general
Tool Plugin registered via `ctx.register_tool`, with a separately injected scoped
`Principal` and `EnterpriseData` backend. Keep episodic recall/semantic persona and
sync hooks in MemoryProvider. Both should use the same Authorizer and audit event
contract. Avoid process-global user bindings. No such split, subagent, alignment
worker, API backend or UI has been implemented here.
