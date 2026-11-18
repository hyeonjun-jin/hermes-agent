"""Paired Hermes Mock workflows using isolated synthetic sources, not an evaluation/scorer."""
import copy
import json
import tempfile
from pathlib import Path

from .config import runtime
from .persona_preferences import preferences


class TechnicalMockReplay:
    mode = 'mock'

    def compare(self, user, baseline, candidate, turn, semantic, *, initial_episodes=(), fixed_revision=None):
        from .application import ResearchApplication, principal
        environment = turn['environment']
        profile, current, _ = runtime(user, environment['topic'], environment['depth'])
        if current != environment or profile != turn['input_snapshot']['profile']:
            return {'mode': 'mock', 'functional_check': False, 'reason': 'Historical server fixture changed'}
        outcomes = {}
        with tempfile.TemporaryDirectory(prefix='technical-persona-replay-') as directory:
            for label, value in (('before', baseline), ('after', {**baseline, 'revision': baseline['revision']+1,
                                                               'preferences': preferences(candidate), 'data_policy': 'PRIVATE'})):
                value = copy.deepcopy(value)
                if fixed_revision is not None:
                    if type(fixed_revision) is not int or fixed_revision < 2:
                        raise ValueError('Controlled replay revision must be an integer >= 2')
                    value['revision'] = fixed_revision
                app = ResearchApplication(Path(directory)/label)
                actor = principal(user)
                app.store.save_semantic(actor, user, copy.deepcopy(semantic))
                with app.store.connect() as db:
                    for episode in initial_episodes:
                        db.execute('INSERT INTO episodes VALUES (NULL,?,?,?,?,?,?)',
                                   (user, episode['session_id'], episode['query'], episode['response'],
                                    int(episode['confirmed']), episode['created_at']))
                    db.execute('INSERT INTO tr_personas VALUES (?,?,?,?)', (user, environment['project_id'], value['revision'], json.dumps(value)))
                    db.execute('INSERT INTO tr_active VALUES (?,?,?)', (user, environment['project_id'], value['revision']))
                result = app.ask(actor, user, turn['question'], topic=environment['topic'], mode=environment['depth'])
                outcomes[label] = {'input': result['input_snapshot'], 'trace': result['trace'], 'stages': result['stages'],
                                   'evidence': result['evidence'], 'checks': result['checks'], 'progress': result['progress'],
                                   'report': result['answer'], 'complete': result['complete'], 'model_calls': result['model_calls']}
        functional = all(value['complete'] and value['model_calls'] <= 12 and
                         all(event['executed'] for event in value['trace']) for value in outcomes.values())
        return {'mode': 'mock', 'functional_check': functional, 'paid_calls': 0, 'external_source_calls': 0,
                'replay_sources': 'SYNTHETIC offline corpus; original documents are not replayed',
                'before': outcomes['before'], 'after': outcomes['after'],
                'behavior_changed': [event['plan'] for event in outcomes['before']['trace']] != [event['plan'] for event in outcomes['after']['trace']],
                'note': 'Scripted responder follows context. This does not establish LLM quality or causal personalization.'}
