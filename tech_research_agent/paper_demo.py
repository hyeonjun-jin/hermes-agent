"""Streamlit's real API action: reuse ResearchApplication, SourceAdapter and all three Hermes loops."""
import copy
import json
import os
from pathlib import Path
import tempfile
import uuid

from .application import ResearchApplication, principal
from .connectors.openalex import OpenAlexConnector
from .paper_demo_approval import PaperDemoApproval, PROFILES_PUBLIC, QUESTION
from .paper_demo_real import PaperDemoAdapter, connection_readiness, demo_plan
from .paper_recommendations import recommend_from_trace
from .environment_resources import source_resources
from .real import RealBlocked
from .approvals import digest


def run_demo(repository, profile, question, *, enabled=False, consent=False, approval_path=None):
    if enabled is not True or consent is not True:
        raise RealBlocked('서버 활성화와 이번 시연 과금/외부 처리 동의가 필요합니다.')
    if profile not in PROFILES_PUBLIC or question != QUESTION:
        raise RealBlocked('검수된 시연 Profile과 화면에 안내된 고정 공개 질문만 허용합니다.')
    approval = PaperDemoApproval(approval_path)
    connection_readiness()
    root, plan = demo_plan(repository, approval)
    adapter = PaperDemoAdapter(root/'usage.json', plan, approval, profile)
    adapter._check_saved_usage(json.loads(adapter.path.read_text()))
    connector = OpenAlexConnector(enabled=True, api_key=os.environ.get('OPENALEX_API_KEY'), api_key_parameter=True)
    try:
        with tempfile.TemporaryDirectory(prefix='isolated-', dir=root) as temporary:
            app = ResearchApplication(temporary, public_real_adapter=adapter, source_connectors={'openalex': connector})
            result = app.ask(principal('researcher'), 'researcher', question, execution_mode='approved_public')
            result['mode'] = 'public_paper_demo'
            result['demo_profile'] = profile
            result['profile'] = copy.deepcopy(PROFILES_PUBLIC[profile])
            result['persona'] = {**result['profile'], 'version': 1, 'approved_preferences': {}}
            result['input_snapshot']['profile'] = copy.deepcopy(result['profile'])
            result['environment']['allowed_sources'] = ['openalex']
            result['environment']['information_resources'] = source_resources(result['environment'])
            result['input_snapshot']['environment'] = copy.deepcopy(result['environment'])
            result['paper_recommendations'] = recommend_from_trace(adapter.public_policy.adapter,
                result['profile'], {}, result['environment'], question)
            # Replace only a legacy source-label constant, never rewrite model content or facts.
            result['answer'] = result['answer'].replace('PUBLIC OpenAlex + SYNTHETIC fixtures / approved_public',
                                                       'PUBLIC OpenAlex / 실제 API 시연')
            result['checks']['data_label'] = 'PUBLIC OpenAlex — 실제 API 시연'
            result['scope'] = 'Reviewed fictional public Profile; fresh empty Persona/Memory; OpenAlex metadata/abstracts only'
    finally:
        connector.close()
    for event in result['trace']:
        if event.get('egress_policy', {}).get('status') == 'denied':
            event['result'] = {'status': 'denied', 'reason': 'public_demo_egress_denied',
                               'denied_result_sha256': digest(event['result'])}
    # Reflected credentials from a denied source must not appear even in local UI/error audit.
    text = json.dumps(result, ensure_ascii=False)
    for key in ('PERSONA_API_KEY', 'OPENALEX_API_KEY', 'OPENAI_API_KEY'):
        value = os.environ.get(key, '').strip()
        if value: text = text.replace(value, '[REDACTED]')
    result = json.loads(text)
    output = root/('report-'+profile+'-'+uuid.uuid4().hex+'.json')
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False)
    output.chmod(0o600)
    return result
