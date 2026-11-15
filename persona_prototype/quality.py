"""Separate observable source/format checks from human semantic review."""
import re

from .evidence import evidence_review


def quality_review(result, prior_sources=()):
    raw = result["raw_answer"]
    environment = [e["result"] for e in result.get("role_tool_calls", [])
                   if e["role"] == "analysis" and e.get("status") == "ok"]
    environment += [e["result"] for e in result.get("tool_calls", [])
                    if e["tool"] == "mock_environment" and e.get("status") == "ok"]
    cited = sorted(set(re.findall(r"\bdoc-\d+\b", result["answer"])))
    known = {d["id"] for e in result.get("role_tool_calls", []) if e["role"] == "research"
             and e.get("status") == "ok" for d in e["result"]}
    known.update(d["id"] for e in result.get("tool_calls", []) if e["tool"] == "mock_rag"
                 and e.get("status") == "ok" for d in e["result"])
    known.update(prior_sources)
    evidence = result.get("source_evidence", {"environment": {"items": environment}})
    raw_review = evidence_review(raw, evidence)
    contradiction = any(i["kind"] in {"known_environment_as_unknown", "environment_fact_conflict"}
                        for i in raw_review["issues"])
    return {"korean_present": bool(re.search(r"[가-힣]", raw)),
            "source_ids": cited, "unsupported_source_ids": sorted(set(cited) - known),
            "observed_environment": environment, "possible_environment_contradiction": contradiction,
            "raw_evidence_review": raw_review,
            "evidence_correction_applied": result.get("evidence_validation", {}).get("applied", False),
            "semantic_review_required": True,
            "fact_grounding": result.get("fact_validation", {"applied": False}),
            "note": "Korean presence and source coverage do not prove semantic accuracy; absence in RAG is not global absence."}
