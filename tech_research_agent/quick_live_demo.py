"""Rapid, isolated live proof-of-concept. Does not change Hermes approvals, state or budgets.

Four real gpt-4o-mini requests at most: forced OpenAlex tool selection, Research,
Analysis, Verification. Only public paper titles/years/DOIs and local ranking scores
go to the model. This is NOT a test of the protected Hermes 3-Agent live runner.
"""
import json
import os
from pathlib import Path

import httpx

from tech_research_agent.config import runtime
from tech_research_agent.paper_ranking import rank_papers

MODEL = "gpt-4o-mini"
OBSERVED_MODEL = "gpt-4o-mini-2024-07-18"
SEARCHES = [
    "hydrogen direct reduction iron steel process",
    "hydrogen based direct reduction iron ore kinetics",
]
MAX_CALLS = 4
calls = []
key = os.environ.get("PERSONA_API_KEY", "").strip()
if not key:
    raise SystemExit("PERSONA_API_KEY가 없습니다. API Key를 출력하거나 파일에 저장하지 마세요.")


def model_call(messages, max_tokens, *, tools=None, tool_choice=None):
    if len(calls) >= MAX_CALLS:
        raise RuntimeError("실험 상한 4회에 도달했습니다.")
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if tools is not None:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice
    # Count a dispatch before sending. Never auto-retry a paid call.
    calls.append({"status": "sent"})
    try:
        res = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": "Bearer " + key},
            json=payload,
            timeout=40,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError("OpenAI 요청 실패(자동 재시도 없음): " + type(exc).__name__) from exc
    if res.status_code != 200:
        raise RuntimeError("OpenAI API HTTP " + str(res.status_code))
    data = res.json()
    calls[-1] = {"model": data.get("model"), "usage": data.get("usage", {})}
    if data.get("model") != OBSERVED_MODEL:
        raise RuntimeError("응답 모델이 이전 실측 ID와 달라 중단: " + str(data.get("model")))
    return data["choices"][0]["message"]


# Research phase: a real model emits a real OpenAI tool_call. To keep this
# short experiment reproducible, the permitted search strings are fixed.
schema = [{
    "type": "function",
    "function": {
        "name": "search_openalex",
        "description": "Search public OpenAlex scholarly-work metadata.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "enum": SEARCHES}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}]
request = model_call(
    [
        {"role": "system", "content": "You are a research agent. Call search_openalex once using one allowed query."},
        {"role": "user", "content": "수소환원제철 관련 기술 논문을 검색해 주세요."},
    ],
    160,
    tools=schema,
    tool_choice={"type": "function", "function": {"name": "search_openalex"}},
)
tool_calls = request.get("tool_calls", [])
if len(tool_calls) != 1 or tool_calls[0].get("function", {}).get("name") != "search_openalex":
    raise RuntimeError("예상한 OpenAlex tool_call이 반환되지 않았습니다.")
query = json.loads(tool_calls[0]["function"]["arguments"]).get("query")
if query not in SEARCHES:
    raise RuntimeError("미승인 검색어: 모델 출력 검증 실패")

# Local tool executor uses real OpenAlex. No private data or API key is sent
# to OpenAI; article abstracts stay local for heuristic ranking only.
_, env, _ = runtime("researcher", "H", "quick")
params = {
    "search": query,
    "filter": "from_publication_date:2024-01-01,to_publication_date:" + env["cutoff"],
    "per_page": 25,
}
if os.environ.get("OPENALEX_API_KEY", "").strip():
    params["api_key"] = os.environ["OPENALEX_API_KEY"].strip()
response = httpx.get("https://api.openalex.org/works", params=params, timeout=30)
response.raise_for_status()
works = response.json().get("results", [])


def rebuild_abstract(inverted):
    tokens = sorted((pos, term) for term, positions in (inverted or {}).items() for pos in positions)
    return " ".join(term for _, term in tokens)


papers = []
for item in works:
    if not item.get("title") or not item.get("publication_date") or not item.get("id"):
        continue
    abstract = rebuild_abstract(item.get("abstract_inverted_index"))
    papers.append({
        "source_id": item["id"].split("/")[-1],
        "title": item["title"],
        "published_at": item["publication_date"],
        "publication_year": item.get("publication_year"),
        "abstract": abstract,
        "abstract_checked": bool(abstract),
        "doi": item.get("doi"),
        "openalex_link": item["id"],
    })

if not papers:
    raise RuntimeError("OpenAlex에서 논문 메타데이터를 받지 못했습니다.")

# Same observed candidates and same project environment for both profiles.
# This is a Profile comparison, NOT a proven approved-Persona comparison.
approved = {"explicitly_approved": False}
rows = {}
for name in ("researcher", "strategy"):
    profile, environment, _ = runtime(name, "H", "quick")
    rows[name] = rank_papers(papers, profile, approved, environment, "수소환원제철 관련 기술 논문 추천")


def compact(row):
    return {
        "rank": row["rank"],
        "title": row["title"],
        "year": row["publication_year"],
        "score": row["score"],
        "profile_matches": row["matched_profile_concepts"],
        "doi": row.get("doi"),
        "openalex": row.get("openalex_link"),
    }


evidence = {
    "question": "수소환원제철 관련 기술 논문 추천",
    "openalex_query": query,
    "cutoff": env["cutoff"],
    "candidates": len(papers),
    "researcher": [compact(x) for x in rows["researcher"]],
    "strategy": [compact(x) for x in rows["strategy"]],
    "limitations": [
        "고정된 Profile fixture 비교: 승인 Persona 효과는 검증하지 않음",
        "제목/메타데이터 기반 보고: 본문 결과나 성능 수치는 확인하지 않음",
        "25개 후보에 대한 휴리스틱 점수: 학술 품질이나 모델의 추천 성능을 나타내지 않음",
    ],
}
evidence_json = json.dumps(evidence, ensure_ascii=False)

research = model_call([
    {"role": "system", "content": "Research Agent. 한국어로 짧게 작성. 제공된 메타데이터만 사용. 논문 제목만으로 실제 연구 결과/성능 수치를 추측하지 마세요."},
    {"role": "user", "content": evidence_json + "\n각 직무별 주요 추천 후보와 제목 수준의 기술적 관련성을 요약하세요."},
], 440).get("content") or ""

analysis = model_call([
    {"role": "system", "content": "Analysis Agent. 한국어. 두 Profile 순위 차이와 그 원인이 휴리스틱 점수에 기인함을 명확히. Persona 개선·모델 자율 선택의 효과로 해석하지 마세요."},
    {"role": "user", "content": evidence_json + "\nResearch 의견:\n" + research + "\n비교 해석과 한계를 간결하게 작성하세요."},
], 480).get("content") or ""

verification = model_call([
    {"role": "system", "content": "Verification Agent. 한국어. 제공된 출처 메타데이터와 텍스트만 기준으로 과장·근거 없는 주장을 점검. 외부 논문 본문을 읽었다고 주장하지 마세요. 마지막에 수석연구원 보고용 결론 3문장을 작성하세요."},
    {"role": "user", "content": evidence_json + "\nResearch:\n" + research + "\nAnalysis:\n" + analysis},
], 420).get("content") or ""


def rank_table(items):
    if not items:
        return "해당 기준을 만족한 후보 없음"
    out = ["| 순위 | 논문 (OpenAlex) | 연도 | 적합도 점수 | Profile 일치 |", "|---|---|---:|---:|---|"]
    for paper in items:
        label = paper["title"].replace("|", "/").replace("\n", " ")
        url = paper["openalex_link"]
        out.append(f"| {paper['rank']} | [{label}]({url}) | {paper['publication_year']} | {paper['score']} | {', '.join(paper['matched_profile_concepts']) or '없음'} |")
    return "\n".join(out)


total_input = sum(x.get("usage", {}).get("prompt_tokens", 0) for x in calls)
total_output = sum(x.get("usage", {}).get("completion_tokens", 0) for x in calls)
report = "\n\n".join([
    "# 실제 OpenAlex × GPT-4o mini: 개인화 추천 신속 검증",
    f"**정보원:** OpenAlex 공개 메타데이터 / **조회 후보:** {len(papers)}건 / **기준일:** {env['cutoff']}",
    f"**검색어:** `{query}`",
    "## Researcher 추천 TOP 3\n" + rank_table(rows["researcher"]),
    "## Strategy 추천 TOP 3\n" + rank_table(rows["strategy"]),
    "## 실제 GPT-4o mini Research 단계\n" + research,
    "## 실제 GPT-4o mini Analysis 단계\n" + analysis,
    "## 실제 GPT-4o mini Verification 단계\n" + verification,
    "## 검증 범위와 제약\n"
    "- GPT-4o mini 실제 유료 요청 4회(검색 function call 1회 + Research/Analysis/Verification 각 1회)\n"
    "- OpenAlex API로 실제 검색, 동일 후보집합의 Profile별 로컬 휴리스틱 순위 비교\n"
    "- 검색 function call은 안전한 두 검색어 중에서 강제 선택. 자율적 도구 선택 성능 실험 아님\n"
    "- 기존 Hermes 3-Agent 승인 실행기와 별개인 신속 PoC. Hermes의 실 Tool Calling 성능 입증 아님\n"
    "- 승인 Persona 선호·PRIVATE Memory를 읽거나 OpenAI로 전송하지 않음\n"
    "- 논문 전문 미열람, GPT-4o mini 검토가 독립적인 사실검증이라는 의미는 아님",
    f"**모델:** {OBSERVED_MODEL} / **입력 토큰:** {total_input} / **출력 토큰:** {total_output}",
])
out = Path(".technical-research-state/quick_live_report.md")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(report + "\n", encoding="utf-8")
print("=== 실제 OpenAlex 조회:", len(papers), "건 ===")
print("=== Researcher TOP 3 ===")
for p in rows["researcher"]:
    print(p["rank"], p["title"], p["score"])
print("=== Strategy TOP 3 ===")
for p in rows["strategy"]:
    print(p["rank"], p["title"], p["score"])
print("\n=== 실제 GPT-4o mini 검증 의견 ===\n" + verification)
print("\n모델 유료 API 호출:", len(calls), "회")
print("입력/출력 토큰:", total_input, "/", total_output)
print("보고서:", out.resolve())
