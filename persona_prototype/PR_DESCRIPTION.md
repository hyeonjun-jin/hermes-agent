# Add Hermes personalization prototype and gated live-model comparison

The prototype runs three synthetic user profiles through the existing Hermes
agent loop with a scoped MemoryProvider, persistent episodic/semantic memory,
and synthetic document/environment tools. The live comparison runner requires
explicit endpoint, model and key environment variables and never falls back to
the deterministic mock when configuration is missing.

Comparison reports include personas, model-generated tool calls, executed tool
arguments/results, memory evidence, environment retrieval and final answers.
Failures, invalid arguments, denied access and empty searches are distinguishable.
No Hermes core, manifests or lockfiles change. No Multi-Agent or web features are
implemented. Fixture users/documents/memory remain entirely synthetic.

## Validation

* Official runner: 15 prototype tests plus 58 representative regression tests.
* Pinned Ruff check over `persona_prototype` and `tests/persona_prototype`.
* Real comparison command returned `blocked_configuration`: required environment
  variables are absent; no external LLM was called. Real-model personalization,
  provider authentication errors and live-model recovery remain unvalidated.
* Offline HTTP model fixtures test the actual Hermes loop and comparison reports;
  they do not demonstrate learned personalization quality.

See `VALIDATION.md` for secure configuration, rerun instructions, attribution of
hardcoded input vs model decisions, and the future Tool Plugin separation.
