"""Synchronous application boundary reusable by a future HTTP backend."""
import json
import uuid
from pathlib import Path

from agent.memory_manager import MemoryManager
from hermes_constants import set_hermes_home_override, reset_hermes_home_override
from run_agent import AIAgent
from .data import PROFILES, PREFERENCES
from .domain import Principal, OwnerOnly
from .provider import PersonaMemoryProvider
from .store import MemoryStore
from .personalization import format_answer
from .fact_grounding import ground_project_facts
from .evidence import collect_evidence, evidence_review, ground_evidence
from .output_format import format_matches
from .runtime_config import ensure_runtime_config

SCOPES = frozenset({"memory:read", "memory:write", "documents:read", "environment:read",
                    "persona:read", "persona:propose", "persona:approve", "persona:rollback"})


def seed(store):
    """Idempotent fixture provisioning, explicit demo-only owner credentials."""
    for user in PROFILES:
        actor = Principal(user, SCOPES)
        if store.semantic(actor, user):
            continue
        store.save_semantic(actor, user, {"format": PROFILES[user]["format"], "source": "explicit mock preference"})
        for i in range(5):
            store.append(actor, user, "fixture", f"프로젝트 계획 {i}",
                         f"focus={PREFERENCES[user]} 확인된 선호", confirmed=True)


class ChatApplication:
    def __init__(self, root: Path, *, base_url: str, api_key: str, model: str, authorizer=None,
                 validation_limits=False, multi_agent=False, provider_class=None):
        self.root = root.resolve()
        self.store = MemoryStore(self.root / "memory.sqlite", authorizer or OwnerOnly())
        self.base_url, self.api_key, self.model = base_url, api_key, model
        self.validation_limits = validation_limits
        self.multi_agent = multi_agent
        self.provider_class = provider_class

    def chat(self, principal: Principal, user_id: str, question: str, *, session_id=None,
             conversation_history=None, persona_snapshot=None, known_source_ids=(), prior_environment=None) -> dict:
        self.store.authorizer.require(principal, user_id, "memory:read")
        if user_id not in PROFILES:
            raise ValueError("Unknown profile")
        home = self.root / "homes" / user_id
        home.mkdir(parents=True, exist_ok=True)
        ensure_runtime_config(home, limited=self.validation_limits or self.multi_agent, multi_agent=self.multi_agent)
        token = set_hermes_home_override(home)
        manager = MemoryManager()
        provider_class = PersonaMemoryProvider
        if self.multi_agent:
            from .multi_agent import MultiAgentProvider
            provider_class = MultiAgentProvider
        provider = (self.provider_class or provider_class)(self.store, principal)
        provider.session_mode = session_id is not None
        provider.question = question
        provider.known_source_ids = set(known_source_ids)
        provider.prior_environment = prior_environment
        session_id = session_id or "persona-" + uuid.uuid4().hex
        agent = None
        role_handles = []
        owner_token = None
        try:
            if self.multi_agent:
                from .multi_agent import register_role_tools
                role_handles = register_role_tools(provider)
            manager.add_provider(provider)
            manager.initialize_all(session_id=session_id, hermes_home=str(home), agent_context="primary")
            if persona_snapshot is not None:
                provider.persona = dict(persona_snapshot)
            agent = AIAgent(base_url=self.base_url, api_key=self.api_key, model=self.model,
                            provider="openai", api_mode="chat_completions", memory_manager=manager,
                            session_id=session_id, user_id=user_id,
                            enabled_toolsets=["memory"] + (["persona_research", "persona_analysis", "persona_verification"] if self.multi_agent else []),
                            skip_context_files=True, skip_background_review=True, quiet_mode=True,
                            max_iterations=4 if self.validation_limits else 6,
                            max_tokens=512 if self.validation_limits else 1024,
                            run_budget_seconds=60 if self.validation_limits else None, save_trajectories=False,
                            ephemeral_system_prompt="Use only supplied prototype tools. Never call the builtin memory tool.")
            if self.multi_agent:
                from .multi_agent import _OWNER_SCOPE
                provider.agent = agent
                # The parent retains capability names for native child-toolset intersection,
                # but specialist-only schemas are absent from its initial model surface.
                allowed = {s["name"] for s in provider.get_tool_schemas()}
                agent.tools = [t for t in agent.tools if t["function"]["name"] in allowed]
                agent.valid_tool_names = {t["function"]["name"] for t in agent.tools}
                owner_token = _OWNER_SCOPE.set(provider)
            result = agent.run_conversation(question, conversation_history=conversation_history)
        finally:
            try:
                if agent is not None:
                    agent.close()
                manager.shutdown_all()
            finally:
                for handle in reversed(role_handles):
                    handle.dispose()
                if owner_token is not None:
                    from .multi_agent import _OWNER_SCOPE
                    _OWNER_SCOPE.reset(owner_token)
                reset_hermes_home_override(token)
        raw_answer = result["final_response"]
        completion = {}
        if self.multi_agent:
            raw_answer, completion = provider.finish(raw_answer)
        raw_answer, facts = ground_project_facts(provider, raw_answer)
        if facts.get("applied") and not facts["grounded"]:
            completion.update(complete=False, quality_review_required=True)
        sources = collect_evidence(provider)
        evidence_audit = {"applied": False, "sources": sources,
                          "raw_review": evidence_review(result["final_response"], sources),
                          "semantic_review_required": True}
        if not facts.get("applied"):
            raw_answer, evidence_audit = ground_evidence(provider, raw_answer, raw_answer=result["final_response"])
        presentation_input = raw_answer
        answer, formatting = format_answer(presentation_input, provider.persona["format"])
        formatting["presentation_input_valid"] = formatting["raw_valid"]
        formatting["raw_valid"] = format_matches(result["final_response"], provider.persona["format"])
        if evidence_audit["raw_review"]["issues"]:
            completion["quality_review_required"] = True
        history = [dict(m) for m in result.get("messages", [])]
        if (facts.get("applied") or evidence_audit["applied"]) and history and history[-1].get("role") == "assistant" and not history[-1].get("tool_calls"):
            # Only the just-generated final message is grounded before becoming session history.
            history[-1]["content"] = answer
        return {"session_id": session_id, "persona": provider.persona,
                "raw_answer": result["final_response"], "presentation_input": presentation_input,
                "answer": answer, "format_validation": formatting,
                "source_evidence": evidence_audit["sources"], "evidence_validation": evidence_audit,
                "recall_events": provider.recall_trace, "tool_calls": provider.trace,
                "history": history, "fact_validation": facts,
                "delegations": getattr(provider, "delegations", []),
                "role_tool_calls": getattr(provider, "role_traces", []), "completion": completion,
                "loop_error": bool(result.get("error") or result.get("failed") or result.get("partial")),
                "model_tool_calls": [tc for m in result.get("messages", [])
                                     if m.get("role") == "assistant" for tc in (m.get("tool_calls") or [])]}


def main():
    import argparse
    import os
    from .mock_llm import mock_endpoint
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/workspace/persona-prototype-state"))
    parser.add_argument("--mode", choices=["mock", "real"], default="mock")
    parser.add_argument("--user", choices=list(PROFILES))
    parser.add_argument("--question", default="현재 프로젝트 계획을 어떻게 진행하면 좋을까요?")
    args = parser.parse_args()

    def run(url, key, model):
        app = ChatApplication(args.root, base_url=url, api_key=key, model=model)
        seed(app.store)
        for user in [args.user] if args.user else PROFILES:
            # CLI fixtures are trusted identities, not production authentication.
            result = app.chat(Principal(user, SCOPES), user, args.question)
            print(json.dumps({"user": user, **result}, ensure_ascii=False, indent=2))

    if args.mode == "mock":
        with mock_endpoint() as url:
            run(url, "mock-only", "persona-mock")
    else:
        from .validation import real_settings
        try:
            settings = real_settings(os.environ)
        except ValueError as exc:
            parser.error(str(exc))
        run(*settings)


if __name__ == "__main__":
    main()
