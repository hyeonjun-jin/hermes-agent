"""Experiment-only Research path: native child, authorized Environment, code source checks."""
import json
import re

from .data import PROFILES
from .evidence import EVIDENCE_RULES
from .fact_grounding import SOURCE_RULES
from .multi_agent import MultiAgentProvider, successful
from .provider import schema


ENTRYPOINT = "comparison_research"


class ComparisonProvider(MultiAgentProvider):
    def system_prompt_block(self):
        profile = {"project_id": PROFILES[self.principal.user_id]["project"], "source": "profile:" + self.principal.user_id}
        return ("PERSONA_JSON=" + json.dumps(self.persona, ensure_ascii=False) + "\nPROFILE_FACTS_JSON=" + json.dumps(profile)
                + "\n" + SOURCE_RULES + EVIDENCE_RULES + "\n"
                "This controlled experiment runs only Main and a native Research child. Call comparison_research once, "
                "then synthesize the returned document originals and authorized Environment. "
                "There are no Analysis/Verification agent runs; source checks are deterministic code. "
                "Use PERSONA_JSON.focus before older recalled search preferences. "
                "Answer in Korean, cite document IDs, distinguish known facts and uncertainty. "
                "Include the exact observed project identifier and stage. "
                "Follow PERSONA_JSON.format: bullets requires '- ' per nonempty line; table requires a Markdown table "
                "with header and separator. Never infer project identity/stage from preference memory.")

    def get_tool_schemas(self):
        return [schema(ENTRYPOINT, "Collect one Research result plus authorized Environment and original-source checks.", {}, [])]

    def main_tool_choice(self, has_results):
        return "none" if has_results else {"type": "function", "function": {"name": ENTRYPOINT}}

    def handle_tool_call(self, tool_name, args, **kwargs):
        if tool_name != ENTRYPOINT or args != {} or self.delegations:
            return json.dumps({"error": "Only one comparison evidence round is allowed"})
        research = json.loads(self.delegate("research"))
        project = PROFILES[self.principal.user_id]["project"]
        event = {"tool": "mock_environment", "args": {"project": project}, "origin": "deterministic_harness"}
        self.trace.append(event)
        try:
            environment = self.backend.environment(self.principal, project)
            originals = []
            for document in self.documents.values():
                matches = self.backend.search(self.principal, document["text"], document["tag"])
                original = next(d for d in matches if d["id"] == document["id"])
                if original != document:
                    raise ValueError("Source changed during comparison")
                originals.append(original)
            if environment.get("project") != project or not environment.get("stage"):
                raise ValueError("Incomplete Environment")
            self.checked.update(d["id"] for d in originals)
            event.update(status="ok", result=environment)
            return json.dumps({"research": research, "environment": environment, "originals": originals,
                               "verification_origin": "deterministic_code_not_a_subagent"}, ensure_ascii=False)
        except (PermissionError, OSError, ValueError, KeyError, StopIteration, TypeError, AttributeError):
            event.update(status="unverified", error="Authorized evidence check failed")
            return json.dumps({"error": "Authorized evidence check failed"})

    def finish(self, answer):
        unknown = set(re.findall(r"\bdoc-\d+\b", answer)) - self.checked
        complete = (successful(self.results.get("research", {})) and bool(self.checked)
                    and self.checked == set(self.documents) and not unknown
                    and any(e.get("status") == "ok" for e in self.trace))
        return answer, {"complete": bool(complete), "roles_run": [e["role"] for e in self.delegations],
                        "checked_document_ids": sorted(self.checked), "unsupported_document_ids": sorted(unknown),
                        "environment_origin": "deterministic_harness", "verification_origin": "deterministic_code",
                        "semantic_review_required": True}
