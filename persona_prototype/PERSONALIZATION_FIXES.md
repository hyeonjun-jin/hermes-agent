# Personalization repair and live observation

## Diagnosis and implementation

The original provider inherited an empty `prefetch()`. Relevant episodes therefore
never entered the turn unless the model voluntarily called `persona_recall`.
That tool was suggested but neither required nor chosen in the original live run.
Free-text RAG tags allowed project IDs, and whitespace matching could not bridge
English queries and Korean fixture documents. Formatting was only a soft prompt.

The repaired flow is:

1. `initialize()` reads the scoped semantic preference and builds an immutable
   persona snapshot. `system_prompt_block()` gives explicit format instructions,
   valid focus tags and a distinction between project IDs and tags.
2. Hermes calls `prefetch()` before inference on nontrivial turns. Scoped lexical
   search returns at most four relevant **confirmed** episodes, or nothing for
   unrelated questions. Hermes fences the JSON in the existing turn-context path;
   no system prompt or past message is rewritten. `persona_recall` remains optional
   for additional retrieval. `recall_events` records both automatic and tool recall.
3. `mock_rag.tag` has an enum. Provider-side validation additionally returns
   `invalid_tag`, distinct from a valid query's `empty` result. `tag_sources` lists
   matching recalled memory IDs; an empty list means no recalled source supports
   the chosen tag, not that provenance has been established.
4. Shared retrieval normalization maps a small explicit vocabulary (project/plan,
   delivery/deployment, risk, onboarding/beginner and their Korean equivalents).
   This is a fixture-scale bilingual baseline, not a translator or vector index.
5. `raw_answer` is preserved. A local format validator retains compliant responses
   or rearranges the same text into bullets or a multi-column table, without another LLM call.
   The current renderer splits HTML line breaks into rows and retains existing multi-column tables.
   `format_validation` distinguishes native adherence from presentation repair.
   The current app records `raw_answer`, `presentation_input` and `answer` separately.
   Source-bound corrections are audited independently; see [FACT_GROUNDING.md](FACT_GROUNDING.md).
   Format validation alone is not a factual-quality or citation validator.

## Tests and live experiment

Official runner: 81 tests passed (23 prototype tests, 58 representative regressions).
Pinned Ruff passed. Tests inspect actual HTTP model requests to verify automatic
context injection and within-session system-prompt stability, relevance and user
isolation, enum/runtime validation, bilingual retrieval, provenance, fallback and
a same-profile/environment memory intervention. Offline fixtures are not evidence
of learned model behavior.

The live command (using existing endpoint/model/key environment bindings) is:

```bash
python -m persona_prototype.mini_validation --memory-control \
  --output $TMPDIR/gpt-4o-mini-personalization-fixed.json
```

The original three baseline conditions run once. An independent fresh fixture
condition then changes only Alice's five confirmed episode response fields from
`focus=delivery` to `focus=risk`. Profile, semantic preference, persona, document
corpus, environment and question remain identical. Fresh fixture timestamps differ
between conditions; this is one matched comparison, not a statistical causal study.

Observed live results:

| Condition | Prefetched focus | Actual tools | RAG documents | Raw format / local fallback |
|---|---|---|---|---|
| Alice baseline | delivery | RAG | doc-1, doc-2 | mixed prose/bullets; fallback |
| Bob baseline | risk | RAG, Environment | doc-3 | prose/bullets; table fallback |
| Carol baseline | onboarding | Environment, RAG | doc-5 | explanation; unchanged |
| Alice memory-only risk | risk | RAG | doc-3 | bullets; unchanged |

Each condition automatically retrieved four confirmed episodes. All RAG calls
used valid tags, returned documents and linked tags to recalled memory IDs.
No model needed an explicit `persona_recall` call in this run. Alice's two
conditions used the same tool type and persona/project but changed tag, query,
document evidence and answer theme (delivery/scheduling -> risk/recovery). Neither
Alice condition queried Environment, so their answer difference cannot be
attributed to different environment tool results. Bob and Carol did retrieve and
reflect their environment. Environment use is still model-selected, not guaranteed.

Usage: 10 upstream calls (Alice 2+2, Bob 3, Carol 3), 40,125 input tokens and
390 output tokens, all HTTP 200. Estimate: $0.00625275 at the runner's provisional
rates, with cached input charged at full price. No retries; all request and
output caps held. The shared per-user limit includes both Alice conditions
(4 total), and the global limit remains 12.

Limitations: raw formatting compliance remains imperfect. The live answers did
not consistently cite document/memory IDs, despite matching retrieved content;
provenance is established by logs rather than reliable inline citations. The
experiment uses only small synthetic fixtures, one sample per condition, and a
limited bilingual dictionary. No alignment worker, multi-agent flow or UI was
added. No claim is made about arbitrary corporate corpora or repeated-run quality.
