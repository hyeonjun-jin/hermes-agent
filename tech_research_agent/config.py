"""Synthetic application identities and server policy; not benchmark cases or Gold."""
import copy
import json
from pathlib import Path
from tech_research_benchmark.policy import ServerContext
from tech_research_benchmark.adapter import OfflineAdapter

DATA = Path(__file__).resolve().parents[1] / 'tech_research_benchmark' / 'data'
PROFILES = {
    'researcher': {'department':'연구소','job':'박사 연구원','expertise':'공정·소재',
                   'interests':['수소환원제철','이차전지 양극재'],'criteria':'원리·실험 조건·재현성·청구항', 'focus':'science'},
    'strategy': {'department':'전략실','job':'임원','expertise':'사업 전략',
                 'interests':['수소환원제철','이차전지 양극재'],'criteria':'경쟁 대안·사업화·시장 근거의 한계','focus':'strategy'},
    'finance': {'department':'재무팀','job':'재무 분석','expertise':'투자·현금흐름',
                'interests':['수소환원제철','이차전지 양극재'],'criteria':'투자 규모·재무 건전성·위험','focus':'finance'},
}
SOURCES = {'openalex','kipris_plus','opendart','posco_ir','internal_mock'}


def runtime(user_id, topic, mode):
    if user_id not in PROFILES or topic not in ('H','B') or mode not in ('quick','deep','restricted'):
        raise ValueError('Unknown development identity/project/environment')
    corpus = json.loads((DATA/'corpus.json').read_text())
    registry = json.loads((DATA/'registry.json').read_text())
    environment = {'project_id':'proj-'+topic,'topic':topic,'purpose':'기술 비교와 다음 의사결정 근거 확보',
                   'deadline':'2026-10-01T12:00:00+09:00' if mode=='quick' else '2026-10-15T18:00:00+09:00',
                   'classification':'RESTRICTED' if mode=='restricted' else 'INTERNAL' if mode=='deep' else 'PUBLIC',
                   'audience':'내부 프로젝트 위원회' if mode=='restricted' else '프로젝트 책임자',
                   'as_of':'2026-10-01','cutoff':'2026-09-30','depth':mode,
                   'allowed_sources':sorted({'internal_mock'} if mode=='restricted' else SOURCES if mode=='deep' else SOURCES-{'internal_mock'})}
    # Identical permissions for all three jobs. No role-derived authorization.
    acl = {sid:{user_id} for sid,s in corpus.items() if s['project_id']==environment['project_id']}
    ctx = ServerContext(user_id,environment['project_id'],{environment['project_id']},set(environment['allowed_sources']),
                        environment['classification'],environment['cutoff'],12,acl,
                        {'00000001' if topic=='H' else '00000002':topic})
    return copy.deepcopy(PROFILES[user_id]), environment, OfflineAdapter(ctx,corpus,registry)
