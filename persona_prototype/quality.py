"""Separate observable source/format checks from human semantic review."""
import re


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
    contradiction = bool(environment and re.search(
        r"Environment 정보가 없습니다|환경 정보를 확인하지 못했습니다|No environment information", raw, re.IGNORECASE))
    return {"korean_present": bool(re.search(r"[가-힣]", raw)),
            "source_ids": cited, "unsupported_source_ids": sorted(set(cited) - known),
            "observed_environment": environment, "possible_environment_contradiction": contradiction,
            "semantic_review_required": True,
            "note": "Korean presence and source coverage do not prove semantic accuracy; absence in RAG is not global absence."}
