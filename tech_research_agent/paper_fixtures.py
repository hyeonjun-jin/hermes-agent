"""Standalone application SYNTHETIC papers, never real titles/DOIs or benchmark/Gold changes."""
from .source_adapter import SourceAdapter

PAPERS = (
    ('H-PAPER-EXP', 'H', '2026-05-01', '수소환원제철 실험 조건과 재현성',
     'Hydrogen iron process material reaction mechanism kinetics controlled experiment reproducibility. 공정 소재 환원 원리 반응속도 실험 조건 재현성.'),
    ('H-PAPER-BIZ', 'H', '2026-04-01', '수소환원제철 상용화와 시장 전환',
     'Hydrogen iron industrial scale commercialization market business strategy financial risk comparison. 사업화 시장 전략 재무 위험.'),
    ('H-PAPER-PILOT', 'H', '2026-03-01', '수소환원제철 파일럿 공정 비교',
     'Hydrogen iron process material comparison industrial scale process optimization energy efficiency productivity. 공정 최적화 소재 비교와 상용화 준비. 에너지 효율 생산성.'),
    ('H-PAPER-META', 'H', '2026-09-01', '수소환원제철 논문 메타데이터 표본', None),
    ('B-PAPER-EXP', 'B', '2026-05-01', 'NCM LFP 양극재 실험 조건',
     'NCM LFP cathode material experiment reproducibility. 소재 실험 조건 재현성.'),
    ('B-PAPER-BIZ', 'B', '2026-04-01', 'NCM LFP 양극재 사업화',
     'NCM LFP cathode commercialization market financial risk. 사업화 시장 재무 위험.'),
)


def paper_request(question):
    text = question.casefold()
    return ('논문' in text or 'paper' in text) and ('추천' in text or 'recommend' in text)


def fixture_adapter(base, environment):
    corpus = {key: value for key, value in base.corpus.items() if value['app'] != 'openalex'}
    for identifier, topic, published, title, abstract in PAPERS:
        if topic != environment['topic']:
            continue
        title = 'SYNTHETIC '+title
        spans = [{'id': 'metadata', 'kind': 'metadata', 'text': title}]
        if abstract:
            spans.append({'id': 'abstract', 'kind': 'abstract', 'text': abstract})
        corpus[identifier] = {'id': identifier, 'synthetic': True, 'label': 'SYNTHETIC', 'topic': topic,
            'app': 'openalex', 'kind': 'paper', 'project_id': 'proj-'+topic, 'classification': 'PUBLIC',
            'published_at': published, 'title': title, 'locator': 'fixture://paper-recommendations/'+identifier,
            'spans': spans, 'payload': {'abstract': abstract, 'publication_year': int(published[:4]), 'doi': None}}
    return SourceAdapter(base.context, corpus, base.registry, connectors={})
