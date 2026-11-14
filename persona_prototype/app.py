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

SCOPES = frozenset({"memory:read", "memory:write", "documents:read", "environment:read"})


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
                 validation_limits=False, multi_agent=False):
        self.root = root.resolve()
        self.store = MemoryStore(self.root / "memory.sqlite", authorizer or OwnerOnly())
        self.base_url, self.api_key, self.model = base_url, api_key, model
        self.validation_limits = validation_limits
        self.multi_agent = multi_agent

    def chat(self, principal: Principal, user_id: str, question: str) -> dict:
        self.store.authorizer.require(principal, user_id, "memory:read")
        if user_id not in PROFILES:
            raise ValueError("Unknown profile")
        home = self.root / "homes" / user_id
        home.mkdir(parents=True, exist_ok=True)
        if self.validation_limits or self.multi_agent:
            config = home / "config.yaml"
            if config.exists():
                raise ValueError("Budgeted validation requires a fresh profile home")
            settings = "agent:\n  api_max_retries: 1\n  auto_recovery_cycles: 0\n"
            if self.multi_agent:
                settings += ("delegation:\n  max_iterations: 2\n  max_spawn_depth: 1\n"
                             "  oneshot_max_children: 3\n  max_concurrent_children: 1\n"
                             "  child_timeout_seconds: 45\n  inherit_mcp_toolsets: false\n")
            config.write_text(settings, encoding="utf-8")
        token = set_hermes_home_override(home)
        manager = MemoryManager()
        provider_class = PersonaMemoryProvider
        if self.multi_agent:
            from .multi_agent import MultiAgentProvider
            provider_class = MultiAgentProvider
        provider = provider_class(self.store, principal)
        provider.question = question
        session_id = "persona-" + uuid.uuid4().hex
        agent = None
        role_handles = []
        owner_token = None
        try:
            if self.multi_agent:
                from .multi_agent import register_role_tools
                role_handles = register_role_tools(provider)
            manager.add_provider(provider)
            manager.initialize_all(session_id=session_id, hermes_home=str(home), agent_context="primary")
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
            result = agent.run_conversation(question)
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
        answer, formatting = format_answer(raw_answer, provider.persona["format"])
        return {"session_id": session_id, "persona": provider.persona,
                "raw_answer": result["final_response"], "answer": answer, "format_validation": formatting,
                "recall_events": provider.recall_trace, "tool_calls": provider.trace,
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
