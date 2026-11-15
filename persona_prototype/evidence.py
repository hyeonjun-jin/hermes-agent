"""Bounded source audit and additive rendering; never a general semantic verifier."""
import re

from .data import PROFILES
from .fact_grounding import environment_observation
from .output_format import append_table_notes, table_rows

EVIDENCE_RULES = (
    'RAG documents and Environment are independent sources. A document search only establishes what '
    'was found in those queries, never that a fact does not exist. Report a document gap as '
    '해당 검색에서 미발견, 실제 존재 여부 미확인. Retain every observed Environment project, stage and '
    'constraint even when absent from documents. Never label those observed values unknown. '
    'Keep recommendations distinct from observed facts. Do not fill missing dates, numbers or status '
    'by guessing. For tables use 항목/내용/근거 columns where appropriate; no HTML br tags.'
)
_FIELD_NAMES = {
    'project': r'프로젝트(?:\s*(?:이름|명|ID))?|project(?:\s*(?:name|id))?',
    'stage': r'(?:진행\s*)?단계|상태|stage|phase|status',
    'constraint': r'제약(?:\s*조건)?|constraint',
}
_UNKNOWN = r'미확인|알\s*수\s*없|확인(?:할\s*수\s*없|하지\s*못)|정보가?\s*없|없습니다|unknown|unavailable|not\s+(?:known|available|confirmed)'
_STAGE_ALIASES = {'prototype': ('프로토타입',), 'review': ('검토', '리뷰'), 'learning': ('학습',)}


def collect_evidence(provider):
    user = provider.principal.user_id
    project = PROFILES[user]['project']
    documents = {}
    searched = False
    events = provider.trace + getattr(provider, 'role_traces', [])
    for event in events:
        if event.get('tool') not in {'mock_rag', 'persona_research_search'}:
            continue
        if event.get('status') in {'ok', 'empty'}:
            searched = True
            documents.update({d['id']: dict(d) for d in event.get('result', []) if isinstance(d, dict) and 'id' in d})
    environment = environment_observation(provider)
    # The source is a successful current-turn observation, not the fixture or old memory.
    return {'profile': {'source': 'profile:' + user, 'project': project},
            'documents': {'state': 'observed' if documents else 'not_found_in_search' if searched else 'not_checked',
                          'items': list(documents.values()), 'scope': 'current authorized queries only; not global absence'},
            'environment': {'state': 'observed' if environment else 'not_observed',
                            'source': 'environment:' + project if environment else None,
                            'items': [environment] if environment else []}}


def _known_field_issues(text, field, value):
    names = _FIELD_NAMES[field]
    aliases = (str(value), *(_STAGE_ALIASES.get(value, ()) if field == 'stage' else ()))
    clauses = re.split(r'[\n。.!?;|]', text)
    relevant = [c for c in clauses if re.search(names, c, re.IGNORECASE)]
    issues = []
    if any(re.search(_UNKNOWN, c, re.IGNORECASE) for c in relevant):
        issues.append({'kind': 'known_environment_as_unknown', 'field': field, 'expected': value})
    if not any(alias.lower() in text.lower() for alias in aliases):
        issues.append({'kind': 'environment_fact_omitted', 'field': field, 'expected': value})
    if field == 'stage':
        explicit = re.findall(r'(?:' + names + r')\s*[:：=]\s*([\w-]+)', text, re.IGNORECASE)
        for claimed in explicit:
            if claimed not in aliases and not re.search(_UNKNOWN, claimed, re.IGNORECASE):
                issues.append({'kind': 'environment_fact_conflict', 'field': field, 'expected': value, 'claimed': claimed})
    return issues


def evidence_review(text, evidence):
    issues = []
    items = evidence.get('environment', {}).get('items', [])
    for environment in items:
        if re.search(r'(?:Environment|환경)\s*(?:정보|상태|근거)?[^\n.!?。;|]{0,35}(?:' + _UNKNOWN + ')', text, re.IGNORECASE):
            issues.append({'kind': 'known_environment_as_unknown', 'field': 'environment'})
        for field in _FIELD_NAMES:
            if environment.get(field) not in (None, ''):
                issues.extend(_known_field_issues(text, field, environment[field]))
    for clause in re.split(r'[\n。.!?;|]', text):
        if re.search(r'존재하지\s*않|존재하지\s*않음|does\s+not\s+exist|no\s+such', clause, re.IGNORECASE):
            # No source in this prototype proves global nonexistence.
            issues.append({'kind': 'unscoped_absence_claim', 'statement': clause.strip()})
    return {'issues': issues, 'semantic_review_required': True,
            'scope': 'bounded field/pattern checks; unflagged prose is not verified'}


def ground_evidence(provider, answer, *, raw_answer=None):
    sources = collect_evidence(provider)
    review = evidence_review(answer if raw_answer is None else raw_answer, sources)
    items = sources['environment']['items']
    applied = bool(review['issues'] and (items or any(i['kind'] == 'unscoped_absence_claim' for i in review['issues'])))
    if applied:
        lines = ['모델 초안 (아래 근거 정정과 함께 검토):', answer, '', '조회 근거 정정:']
        profile = sources['profile']
        lines.append(f'프로젝트: {profile["project"]} [{profile["source"]}]')
        for environment in items:
            source = sources['environment']['source']
            for field, label in [('stage', '현재 진행 단계'), ('constraint', '현재 제약')]:
                if environment.get(field) not in (None, ''):
                    lines.append(f'{label}: {environment[field]} [{source}]')
        lines.append('검색 범위: 문서 검색에서의 미발견은 실제 부재를 뜻하지 않습니다. 제공되지 않은 값은 미확인입니다.')
        draft_table = raw_answer if raw_answer is not None else answer
        if table_rows(draft_table) and answer.startswith(draft_table):
            notes = [('로컬 검토 안내', '앞선 모델 초안에는 검토 항목이 있습니다. 아래 조회 근거를 우선합니다.')]
            suffix = answer[len(draft_table):].strip()
            if suffix:
                notes.append(('실행 검토', suffix.replace('\n', ' ')))
            notes.extend(('조회 근거 정정', line) for line in lines[4:])
            answer = append_table_notes(draft_table, notes)
        else:
            answer = '\n'.join(lines)
    return answer, {'applied': applied, 'sources': sources, 'raw_review': review,
                    'semantic_review_required': True,
                    'method': 'append observed fields only; draft retained, not semantically certified'}
