"""Explainable local heuristics for papers. No learned weights, model calls or quality claims."""
import re
from datetime import date, datetime

from .persona_preferences import preferences

CONCEPTS = {
    '실험 조건': ('experiment', 'controlled conditions', '실험', '시험 조건'),
    '재현성': ('reproducib', '재현성'), '원리': ('mechanism', '원리'),
    '공정': ('process', '공정'), '소재': ('material', '소재'),
    '사업화': ('commercial', 'industrial scale', '상용화', '사업화'),
    '시장': ('market', '시장'), '사업 전략': ('business', 'strategy', '사업', '전략'),
    '비교': ('comparison', 'compare', '비교', '경쟁', '대안'),
    '위험': ('risk', '위험'), '재무': ('financial', 'finance', '재무', '투자'),
    '청구 범위': ('claim scope', '청구항'),
}
CRITERIA = {'experimental_conditions': {'실험 조건'}, 'reproducibility': {'실험 조건', '재현성'},
            'claim_scope': {'청구 범위'}, 'condition_matched_comparison': {'실험 조건', '비교'},
            'commercialization': {'사업화', '시장'}, 'financial_risk': {'재무', '위험'}}
TOPICS = {'H': ('hydrogen', 'iron', 'steel', '수소환원', '제철'),
          'B': ('ncm', 'lfp', 'cathode', '양극재', '고니켈')}


def concepts(text):
    text = text.casefold()
    return {name for name, words in CONCEPTS.items() if any(word in text for word in words)}


def approved_preferences(approved):
    if approved.get('explicitly_approved') is not True:
        return {}
    return preferences(approved.get('research_persona', {}).get('preferences', {}))


def score_paper(paper, profile, approved, environment, question):
    text = (paper['title']+' '+(paper.get('abstract') or '')).casefold()
    found = concepts(text)
    expertise = concepts(' '.join(str(profile.get(k, '')) for k in ('expertise', 'job', 'criteria')))
    matched = sorted(found & expertise)
    prefs = approved_preferences(approved)
    criteria = [key for key in prefs.get('criteria', []) if found & CRITERIA[key]]
    topic_match = any(bool(re.search(r'\b'+re.escape(word)+r'\b', text)) if word.isascii() else word in text
                      for word in TOPICS[environment['topic']])
    question_terms = set(re.findall(r'\w+', question.casefold()))
    lexical = len(question_terms & set(re.findall(r'\w+', text)))
    purpose = sorted(found & concepts(environment['purpose']))
    published = date.fromisoformat(paper['published_at'])
    as_of = min(date.fromisoformat(environment['as_of']), date.fromisoformat(environment['cutoff']))
    days = (datetime.fromisoformat(environment['deadline']).date()-date.fromisoformat(environment['as_of'])).days
    urgent = 0 <= days <= 3
    detailed = any(prefs.get(k) == 'detailed' for k in ('depth', 'technical_detail', 'business_detail', 'financial_detail'))
    completeness = (2+int(bool(paper.get('publication_year')))+int(bool(paper.get('doi')))
                    +3*int(paper['abstract_checked']))
    components = {
        'project_relevance': float(6+min(2, lexical)+2*min(2, len(purpose))) if topic_match else 0.0,
        'profile_expertise': float(2*min(5, len(matched))),
        'persona_criteria': float(5*min(3, len(criteria))+int('openalex' in prefs.get('preferred_apps', []))),
        'recency': round(4*max(0, 1-(as_of-published).days/(365*3))*(1.25 if urgent else 1), 3),
        'metadata_completeness': completeness*(1+0.5*detailed+0.5*(urgent or environment['depth'] == 'quick')),
    }
    reasons = ['프로젝트 주제 일치' if topic_match else '질문·조사 목적의 검색어 일치',
               'Profile 일치: '+(', '.join(matched) or '추가 전문성 일치 없음'),
               '승인 Persona 기준: '+(', '.join(criteria) or '해당 기준의 명시적 일치 없음'),
               '기준일 대비 '+str((as_of-published).days)+'일 경과',
               '초록 확인' if paper['abstract_checked'] else '메타데이터만 확인: 초록 미확인']
    return {**paper, 'score': round(sum(components.values()), 3), 'score_components': components, 'reasons': reasons,
            'matched_profile_concepts': matched, 'matched_persona_criteria': criteria,
            'environment_basis': {'project_id': environment['project_id'], 'purpose_concepts': purpose,
                'as_of': environment['as_of'], 'cutoff': environment['cutoff'], 'deadline': environment['deadline'],
                'depth': environment['depth'], 'urgent_deadline': urgent},
            'persona_basis': {'criteria': prefs.get('criteria', []), 'detailed_metadata_preference': detailed},
            'full_text_read': False, 'method': 'deterministic_heuristic_v1', 'learning_effect_established': False}


def rank_papers(papers, profile, approved, environment, question, *, limit=3):
    ranked = [score_paper(p, profile, approved, environment, question) for p in papers]
    ranked = [p for p in ranked if p['score_components']['project_relevance'] > 0]
    ranked.sort(key=lambda p: (-p['score'], -date.fromisoformat(p['published_at']).toordinal(), p['source_id']))
    return [{**paper, 'rank': i+1} for i, paper in enumerate(ranked[:limit])]
