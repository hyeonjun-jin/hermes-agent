"""Bounded bilingual keyword matching; advisory lenses, never facts or access grants."""
import re

FACETS = {
    'reaction_mechanism': ('반응 메커니즘', '메커니즘', '환원 원리', '환원 기구', 'reaction mechanism', 'mechanism'),
    'reaction_kinetics': ('반응속도', '반응 속도', '반응속도론', 'kinetics', 'reaction rate'),
    'process_optimization': ('공정 최적화', '공정최적화', 'process optimization', 'process optimisation'),
    'energy_efficiency': ('에너지 효율', '에너지효율', 'energy efficiency'),
    'productivity': ('생산성', 'productivity', 'throughput'),
    'commercialization': ('사업화', '상용화', 'commercialization', 'commercialisation', 'industrial scale'),
    'market': ('시장 동향', '시장', 'market'),
}
LABELS = {'reaction_mechanism': '반응 메커니즘·환원 원리', 'reaction_kinetics': '반응속도·실험 조건',
          'process_optimization': '공정 조건·최적화', 'energy_efficiency': '에너지 효율',
          'productivity': '생산성', 'commercialization': '상용화·산업 적용', 'market': '시장 근거·한계'}
TOPIC_TERMS = {'H': ('수소환원', 'hydrogen', '제철', 'steel'), 'B': ('ncm', 'lfp', '양극재', 'cathode')}
STOP = {'수소환원', '수소환원제철', 'hydrogen', 'steel', 'iron', 'ncm', 'lfp', 'cathode', '양극재', '이차전지', '관심', '기술'}


def contains(text, term):
    return bool(re.search(r'\b'+re.escape(term)+r'\b', text.casefold())) if term.isascii() else term in text


def facets(text):
    return {key for key, words in FACETS.items() if any(contains(text.casefold(), word) for word in words)}


def interest_view(profile, environment, question):
    """Explicit question focus and current business purpose suppress conflicting interests."""
    forced = facets(question) or facets(environment['purpose'])
    active, terms, suppressed = set(), set(), []
    for interest in profile.get('interests', []):
        text = interest.casefold()
        domains = {topic for topic, words in TOPIC_TERMS.items() if any(contains(text, w) for w in words)}
        found = facets(text)
        if (domains and environment['topic'] not in domains) or (forced and not found & forced):
            suppressed.append(interest)
            continue
        active.update(found & forced if forced else found)
        if not found and not forced:
            terms.update(t for t in re.findall(r'\w+', text) if len(t) >= 3 and t not in STOP)
    return {'facets': sorted(active), 'keywords': sorted(terms), 'suppressed': suppressed,
            'explicit_focus': sorted(forced), 'analysis_lenses': [LABELS[k] for k in sorted(forced or active)],
            'priority': 'server_policy > question/environment > approved_persona > profile_interests > history',
            'method': 'bilingual_keyword_rules_not_semantic_model'}


def interest_score(text, profile, environment, question):
    view = interest_view(profile, environment, question)
    matched = sorted(set(view['facets']) & facets(text))
    keywords = [word for word in view['keywords'] if contains(text.casefold(), word)]
    return min(24, 8*len(matched)+2*len(keywords)), {**view, 'matched_facets': matched, 'matched_keywords': keywords}


def search_hint(profile, environment, question):
    view = interest_view(profile, environment, question)
    # Hints are appended by the Mock fixture only. Real Hermes models choose their own tool/arguments.
    return ' '.join(FACETS[key][0] for key in view['facets'])+' '+' '.join(view['keywords'])
