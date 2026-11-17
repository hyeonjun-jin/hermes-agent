"""Consent -> bounded consensus -> paired local replay -> explicit activation. No optimizer LLM."""
import json
from collections import Counter

from .approvals import digest
from .persona_preferences import preferences
from .persona_replay import TechnicalMockReplay


class ResearchPreferenceAligner:
    def __init__(self, repository, replay=None):
        self.repository = repository
        self.replay = replay or TechnicalMockReplay()
        if self.replay.mode != 'mock':
            raise ValueError('Only offline technical replay is implemented')

    def propose(self, actor, project='proj-H'):
        baseline = self.repository.current(actor, project)
        examples = self.repository.examples(actor, project)
        semantic = self.repository.store.semantic(actor, actor.user_id)
        candidate = preferences(baseline['preferences'])
        payload = {'baseline': baseline, 'legacy_sha256': digest(semantic), 'feedback_snapshot': examples,
                   'candidate_preferences': candidate, 'replay': {'mode': 'mock', 'functional_check': False,
                   'note': 'Functional offline replay only; no measured preference improvement'}}
        status = 'insufficient_feedback'
        if len(examples) >= 4:
            training, heldout = examples[:-1], examples[-1]
            keys = set().union(*(example['feedback']['changes'] for example in training))
            for key in keys:
                votes = Counter(json.dumps(example['feedback']['changes'][key], sort_keys=True) for example in training
                                if key in example['feedback']['changes'])
                if len(votes) == 1 and sum(votes.values()) >= 3:
                    candidate[key] = json.loads(next(iter(votes)))
            preferences(candidate)
            changed = {key for key in candidate if candidate[key] != baseline['preferences'].get(key)}
            payload['training_turn_ids'] = [example['turn_id'] for example in training]
            payload['heldout_turn_id'] = heldout['turn_id']
            status = 'no_change' if not changed else 'conflicting_feedback'
            if changed and all(heldout['feedback']['changes'].get(key) == candidate[key] for key in changed):
                payload['replay'] = self.replay.compare(actor.user_id, baseline, candidate, heldout['turn'], semantic)
                status = 'proposed' if payload['replay']['functional_check'] else 'replay_failed'
        return self.repository.save_proposal(actor, project, payload, status)
