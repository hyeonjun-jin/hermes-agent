# Native Hermes specialist prototype

`ChatApplication(..., multi_agent=True)` keeps the personalization MemoryProvider
and existing AIAgent loop. Main's `delegate_specialist` adapter calls the **actual**
`tools.delegate_tool.delegate_task` to create native Hermes child AIAgents. There
is no second inference/retry loop and no Hermes core-file change.

## Roles and boundaries

| Role | Permitted tool | Context supplied |
|---|---|---|
| Research | `persona_research_search` | Question, language, one confirmed focus tag + memory ID |
| Analysis | `persona_analysis_environment` | Question, project field, retrieved documents, bounded research summary |
| Verification | `persona_verify_document` | Original documents, observed environment evidence, bounded research/analysis summaries |

Research searches the authorized Mock RAG backend. Analysis queries the user's
authorized project environment. Verification re-reads all Research document IDs
through the same authorized backend; its no-argument tool cannot request an
arbitrary document or another user's project. Environment evidence is carried in
a distinct channel. Subagents receive neither the user's full episodes/history nor
a personal-memory writer. Native children skip memory providers; only Main syncs
the completed user conversation.

Tools register through `PluginContext.register_tool` in the user's Hermes profile
scope. Stateless handlers resolve `ContextVar` bindings established by the adapter;
native Hermes propagates those bindings to child workers. Handler-side role,
home, principal, scope and project checks remain authoritative. Registration handles
are disposed after the request. This is an embedded, runtime Tool Plugin adapter,
not an installed plugin package or OS sandbox.

An `llm_request` middleware exposes fixed, explicit tools for each role, avoiding
the generic `tool_search` discovery detour. Tool schemas remain stable within the
session. Each specialist gets one tool round followed by a summary, using
`tool_choice=required` then `none`; these are call controls, not system-prompt
rewrites. For an explicit Korean request containing investigation, analysis and
verification, Main exposes the workflow tool and calls it once. The adapter runs
three native delegations sequentially and Main synthesizes their results. Simple
questions retain direct-answer capability. Thus full-workflow routing is partly
an application policy, not a learned autonomous routing capability.

Partial individual-role calls are supported in order, but conservative completion
requires all three roles for a delegated response. Arbitrary task-specific semantic
completion remains a future concern. Do not claim partial workflows passed a full
verification pipeline.

## Completion, citations and audit

`delegations` contains role context, native child result, subagent ID, exit reason,
truncation, usage and native tool trace. `role_tool_calls` contains executed tool
arguments and authorized results. Native live-transcript paths are ephemeral and
are removed with the validation runner's temporary state; JSON preserves the
exported evidence.

Completion requires non-truncated native success, environment retrieval, all
retrieved documents rechecked and no unknown document IDs in the final answer.
Checked source IDs are appended to the returned answer if needed. This is a
mechanical execution/evidence-coverage check, not a proof of factual correctness.
`quality_review_required` remains true. The raw model response is retained, and
local formatting does not generate new facts. Tests round-trip numbers, dates,
uncertainty, document IDs and pipe/newline characters through both output shapes.

## Run and budgets

After the activation instructions in README and secure environment-variable setup:

```bash
scripts/run_tests.sh -j 2 tests/persona_prototype/ -q
python -m persona_prototype.multi_validation --output /tmp/multi-agent-validation.json
```

The runner validates OpenAI / gpt-4o-mini configuration and network grants before
calling a model. It never substitutes Mock. The shared upstream cap is 12 across
Main and all children; final complex workflow uses Main 2 calls and each specialist
2, plus at most 1 direct greeting call. Max output is 512 tokens per call; HTTP
retries are zero; first upstream failure closes the budget. Agent caps also close
it. Single-agent `mini_validation` limits remain unchanged. Use `--complex-only
--max-total 8` for a complex-only check. Usage is measured at the shared gateway,
not by summing potentially incomplete agent self-reports.

## Validation evidence and limitations

Offline tests exercise native parent/child loops, ordered individual roles and a
single workflow call, actual HTTP tool surfaces, role/home/principal denial,
cross-user concurrent role handlers, source coverage, incomplete/truncated results,
simple direct answers, caps and lossless presentation transforms.

Live development observations (all synthetic data, gpt-4o-mini):

1. Initial 4 calls: Main bypassed early roles due competing single-agent instructions;
   completion correctly failed. A greeting took 1 of those calls, with no children.
2. Next 2 calls: generic tool discovery consumed Main's cap. No child role ran.
3. Next 5 calls: native Research completed and Analysis read the environment, but
   repeated tool requests exhausted the role cap. Truncated native results were
   subsequently excluded from success checks.
4. Final 8-call experiment: Main selected workflow; Research retrieved doc-1/doc-2
   using the memory-derived delivery tag; Analysis read atlas/prototype/small-unit
   deployment; Verification re-read both original documents and reported gaps;
   Main returned a source-cited response. All native roles completed normally.

Final successful execution usage: 39,810 input / 802 output tokens, estimated
$0.00645270. **All development attempts combined:** 19 actual upstream calls,
91,483 input / 1,443 output tokens, estimated $0.01458825. This exceeded the initial
announced 12-call task plan while diagnosing and fixing routing and repeated-tool
behavior; it is reported explicitly rather than hidden as retries. Each individual
run obeyed its hard cap, and all actual upstream responses were HTTP 200. Reported
429s were local budget rejections, not OpenAI rate limits. Pricing is provisional
and cached input is charged at full input rate, as in the existing runner.

The final live answer was English despite the Korean persona, and some role
summaries/Main conflated missing document details with environment data already
available. Structural execution passed, but full semantic verification and language
adherence did not. Explicit language instructions and separate Environment evidence
in the verification tool result were added **after** that live experiment and
validated offline only; no further paid call was made. The direct greeting was
observed on the initial version and tested offline on the final version, without
another live greeting. Only Alice was used for the multi-agent live experiment;
cross-user role isolation was tested offline, not in simultaneous live sessions.

The current implementation is sequential, fixture-backed, and not a production
fact checker. More robust structured claim/source contracts and quality evaluation
are needed before production. No web UI or Test-Time Alignment is implemented.
