"""Explicit, once-only real API validation. Requires a fresh 12-call backend budget."""
import argparse
import json
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8001")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {"mode": "real", "model": "gpt-4o-mini", "cases": [], "semantic_review_required": True}
    with httpx.Client(base_url=args.api, timeout=180) as client:
        health = client.get("/health").json()
        if health["mode"] != "real" or health["usage"]["upstream_attempts"] != 0 or health["remaining_calls"] != 12:
            print("Refusing validation: requires a real backend with a fresh, explicitly allocated 12-call budget.")
            return 2
        report["initial_usage"] = health
        sessions = {}
        cases = [("alice", "complex", "현재 프로젝트 계획을 관련 문서로 조사하고, 환경과 제약에 맞춰 분석한 뒤 근거와 누락 정보를 검증해 주세요."),
                 ("alice", "followup", "방금 대화에서 확인한 프로젝트 이름과 배포 제약을 한국어 한 문장으로 다시 알려주세요. 새 도구 호출 없이 이전 대화만 참고하세요."),
                 ("bob", "persona", "도구를 호출하지 말고 Persona에 있는 프로젝트명과 선호 응답 형식만 한국어로 알려주세요."),
                 ("carol", "persona", "도구를 호출하지 말고 Persona에 있는 프로젝트명과 선호 응답 형식만 한국어로 알려주세요.")]
        for user, case, question in cases:
            health = client.get("/health").json()
            if health["stopped"] or health["remaining_calls"] == 0:
                break
            if user not in sessions:
                response = client.post("/dev/sessions", json={"user": user})
                response.raise_for_status()
                sessions[user] = response.json()
            session = sessions[user]
            response = client.post(f'/sessions/{session["session_id"]}/messages',
                                   headers={"Authorization": "Bearer " + session["session_token"]},
                                   json={"message": question})
            report["cases"].append({"user": user, "case": case, "question": question,
                                    "http_status": response.status_code, "result": response.json()})
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if response.status_code != 200 or response.json().get("loop_error"):
                break
        report["audit"] = client.get("/dev/audit").json()
        report["final_usage"] = client.get("/health").json()
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Report: " + str(args.output))
    return 0 if len(report["cases"]) == 4 and all(
        r["http_status"] == 200 and not r["result"].get("loop_error") for r in report["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
