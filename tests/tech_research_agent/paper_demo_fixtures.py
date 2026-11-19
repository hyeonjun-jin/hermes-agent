"""FABRICATED demo authorizations, models and OpenAlex bytes; never live credentials/approval."""
import copy
import json

import httpx

from tech_research_agent.approvals import digest
from tech_research_agent.connectors.openalex import OpenAlexConnector
from tech_research_agent.paper_demo_approval import SNAPSHOT, review_scope


def approval_record():
    return {'approval_id': 'FABRICATED-demo-test', 'approved_by': 'TEST ONLY NOT ACTUAL AUTHORIZATION',
            'actual_execution_approved': True, 'source_access_approved': True, 'public_processing_approved': True,
            'model_identity_reviewed': True, 'scope_sha256': digest(review_scope()),
            'response_model_evidence_sha256': digest('FABRICATED response identity evidence'),
            'max_new_calls': 12, 'max_reserved_usd': 0.12,
            'approved_at': '2020-01-01T00:00:00+00:00', 'expires_at': '2100-01-01T00:00:00+00:00'}


class DemoStub:
    def __init__(self):
        self.requests = []
        self.counts = dict.fromkeys(('research', 'analysis', 'verification'), 0)

    def __call__(self, body):
        self.requests.append(copy.deepcopy(body))
        ctx = json.JSONDecoder().raw_decode(body['messages'][0]['content'].split('TECH_CONTEXT=', 1)[1])[0]
        role = ctx['role']; self.counts[role] += 1
        step = self.counts[role]
        actions = []
        if role == 'research' and step == 1:
            focus = 'mechanism' if '메커니즘' in ctx['profile']['interests'][0] else 'process optimization'
            actions = [('openalex__search_works', {'rp': {'query': 'hydrogen '+focus}, 'op': {'limit': 3}})]
        if (role == 'research' and step == 2) or (role == 'verification' and step == 1):
            actions = [('openalex__read_work', {'rp': {'work_id': identifier}, 'op': {'include_abstract': True}})
                       for identifier in ('W123', 'W456', 'W789')]
        message = {'role': 'assistant', 'content': '테스트 응답: [W123] [W456] [W789] 제공된 초록 범위에서 비교하며 실제 성능과 PDF 본문은 미확인입니다.'}
        if actions:
            message = {'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': role+str(step)+'-'+str(i), 'type': 'function',
                 'function': {'name': name, 'arguments': json.dumps(args)}} for i, (name, args) in enumerate(actions)]}
        message['annotations'] = []  # Known empty provider metadata; no URL or evidence authority.
        return 200, {'id': 'FABRICATED-demo', 'created': 1, 'model': SNAPSHOT,
                     'choices': [{'message': message, 'finish_reason': 'tool_calls' if actions else 'stop'}],
                     'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}


def connector(requests, *, handler=None):
    topics = {'W123': 'reaction mechanism', 'W456': 'process optimization', 'W789': 'industrial scale comparison'}
    works = {key: {'id': 'https://openalex.org/'+key, 'title': 'FABRICATED TEST hydrogen '+value,
             'publication_date': '2026-02-01', 'publication_year': 2026, 'doi': None,
             'abstract_inverted_index': {word: [index] for index, word in enumerate(('Hydrogen iron material '+value).split())}}
             for key, value in topics.items()}
    def send(request):
        requests.append(request)
        if handler: return handler(request)
        return httpx.Response(200, json={'results': list(works.values())} if request.url.path == '/works' else
                              works[request.url.path.rsplit('/', 1)[-1]])
    return OpenAlexConnector(enabled=True, transport=httpx.MockTransport(send), clock=lambda: '2026-11-19T00:00:00+00:00')
