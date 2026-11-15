"""Opt-in bounded preference fitting. No LLM optimizer and no automatic activation."""
from collections import Counter

from .alignment_store import AlignmentStore
from .data import PROFILES
from .store import build_persona
from .alignment_replay import MockReplay


COMMENT_PREFERENCES = {
    "응답은 표로 보여주세요": {"format": "table"},
    "응답은 글머리표로 보여주세요": {"format": "bullets"},
    "응답은 설명형으로 보여주세요": {"format": "explanation"},
    "위험 중심으로 검색해주세요": {"focus": "risk"},
    "배포 중심으로 검색해주세요": {"focus": "delivery"},
    "온보딩 중심으로 검색해주세요": {"focus": "onboarding"},
}


class PreferenceAligner:
    def __init__(self, store, replay=None):
        if replay is not None and replay.mode != "mock":
            raise ValueError("Only offline Mock replay is implemented")
        self.repository = AlignmentStore(store)
        self.replay = replay or MockReplay()

    def propose(self, actor):
        baseline = self.repository.current(actor)
        examples = self.repository.examples(actor)
        report = {"mode": "mock", "improved": False, "feedback_snapshot": examples,
                  "note": "Deterministic Mock replay, not evidence of real LLM preference improvement."}
        candidate = dict(baseline["preferences"])
        if len(examples) < 4:
            report["reason"] = "Need at least four distinct consented turns (three fitting, one held out)"
            return self.repository.save_run(actor, baseline, candidate, report, "insufficient_feedback")
        training, heldout = examples[:-1], examples[-1]
        for key in ("format", "focus"):
            votes = Counter(e["preferences"][key] for e in training if key in e["preferences"])
            if len(votes) == 1 and sum(votes.values()) >= 3:
                candidate[key] = next(iter(votes))
        report.update(training_ids=[e["feedback_id"] for e in training], heldout_id=heldout["feedback_id"])
        if candidate == baseline["preferences"]:
            report["reason"] = "No consistently repeated change to active preferences"
            return self.repository.save_run(actor, baseline, candidate, report, "no_change")
        changed = {key for key, value in candidate.items() if baseline["preferences"].get(key) != value}
        if changed - set(heldout["preferences"]):
            report["reason"] = "Held-out feedback must cover every changed preference field"
            return self.repository.save_run(actor, baseline, candidate, report, "rejected")
        persona = build_persona(PROFILES[actor.user_id], {**candidate, "persona_version": baseline["revision"] + 1})
        comparison = self.replay.compare(actor.user_id, baseline["persona"], persona, heldout)
        report.update(comparison)
        return self.repository.save_run(actor, baseline, candidate, report, "proposed" if report["improved"] else "rejected")
