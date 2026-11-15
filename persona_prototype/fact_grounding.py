"""Narrow, deterministic source contract for project identity and project stage.

This is a safety policy and renderer, not an LLM semantic verifier or agent loop.
"""
import re

from .data import PROFILES


SOURCE_RULES = (
    "Profile.project is the user's project identifier, not the repository/cwd name. "
    "Memory focus=delivery/risk/onboarding and response format are user preferences, never project stages. "
    "Only an authorized Environment observation establishes stage/status. "
    "For a simple current stage/status question Main must call mock_environment directly with Profile.project; "
    "no Research/Analysis/Verification workflow is needed. For an explicitly historical question use an "
    "already observed session snapshot, label it as historical, and never present it as current. "
    "If the requested fact is unverified, say 미확인. Do not infer it from Memory or repository metadata."
)


def fact_policy(question):
    text = question.lower()
    if all(w in text for w in ("조사", "분석", "검증")):
        return {"route": "workflow", "project": False, "stage": False, "historical": False}
    stage = bool(re.search(
        r"진행\s*(?:단계|상태|상황)|현재\s*(?:프로젝트\s*)?(?:진행\s*)?(?:단계|상태|상황)|"
        r"프로젝트\s*(?:상태|단계)|어느\s*단계|어떤\s*단계|"
        r"\bstage\b|\bproject status\b|\bcurrent\s+(?:status|phase)\b", text))
    project = stage or bool(re.search(
        r"프로젝트\s*(?:이름|명|식별자)|\bproject\s+(?:name|id|identifier)\b", text))
    historical = bool(re.search(r"방금|앞서|이전|아까|조회\s*당시|previous|earlier", text)) and not bool(
        re.search(r"현재|최신|지금|새로|다시\s*조회|current|latest|now", text))
    route = "direct_environment" if stage and not historical else "known_facts" if project else "auto"
    return {"route": route, "project": project, "stage": stage, "historical": historical}


def environment_observation(provider):
    project = PROFILES[provider.principal.user_id]["project"]
    observations = [e for e in provider.trace if e["tool"] == "mock_environment"]
    observations += [e for e in getattr(provider, "role_traces", [])
                     if e.get("role") == "analysis" and e.get("tool") == "persona_analysis_environment"]
    for event in reversed(observations):
        value = event.get("result")
        if (event.get("status") == "ok" and event.get("args", {}).get("project") == project
                and isinstance(value, dict) and value.get("project") == project):
            return dict(value)
    return None


def ground_project_facts(provider, raw):
    policy = fact_policy(provider.question)
    if policy["route"] not in {"direct_environment", "known_facts"}:
        return raw, {"applied": False, "route": policy["route"], "scope": "project identity/stage only"}
    user = provider.principal.user_id
    project = PROFILES[user]["project"]
    issues = []
    sources = {"project": {"source": "profile:" + user, "value": project}}
    lines = [f"프로젝트 이름: {project} [profile:{user}]"]
    if project not in raw:
        issues.append("project_value_not_grounded_in_profile")
    if policy["stage"]:
        environment = environment_observation(provider)
        if policy["historical"] and environment is None:
            # Session snapshots are supplied only by the authenticated server, never by request bodies.
            environment = getattr(provider, "prior_environment", None)
            if environment:
                try:
                    provider.store.authorizer.require(provider.principal, user, "environment:read")
                except PermissionError:
                    environment = None
        if not isinstance(environment, dict) or environment.get("project") != project:
            environment = None
        stage = environment.get("stage") if environment else None
        stage = stage if isinstance(stage, str) and stage.strip() else None
        if stage:
            source = ("session-environment:" if policy["historical"] else "environment:") + project
            sources["stage"] = {"source": source, "value": stage}
            label = "이전 조회 당시 단계 (현재 상태 미확인)" if policy["historical"] else "현재 진행 단계"
            lines.append(f"{label}: {stage} [{source}]")
            if stage not in raw:
                issues.append("stage_value_not_grounded_in_environment")
        else:
            sources["stage"] = {"source": None, "value": None}
            lines.append("진행 단계: 미확인 (권한 있는 Environment 조회 근거 없음)")
            issues.append("missing_environment_evidence")
        if re.search(r"(?:단계|상태|stage)\s*[:：=][^\n]*?(?:선호|delivery|risk|onboarding)", raw, re.IGNORECASE):
            issues.append("preference_presented_as_environment_fact")
    answer = "\n".join(lines)
    return answer, {"applied": True, **policy, "sources": sources, "issues": issues,
                    "grounded": not policy["stage"] or sources["stage"]["source"] is not None,
                    "renderer": "source-bound project fields; separate from lossless format conversion"}
