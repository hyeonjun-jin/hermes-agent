"""Four DEV-only offline examples; no evaluation case or Gold loading."""
import json
from .offline import DATA, load
from .adapter import OfflineAdapter
from .policy import ServerContext


def demo():
    corpus = load(DATA / 'development/corpus.json')
    registry = load(DATA / 'registry.json')
    context = ServerContext('dev-user','proj-B',{'proj-B'},{'internal_mock','openalex'},
                            'INTERNAL','2026-09-30',6,{sid:{'dev-user'} for sid in corpus},{'00000002':'B'})
    adapter = OfflineAdapter(context,corpus,registry)
    normal = {'id':'normal','app':'internal_mock','api':'search_documents',
              'rp':{'query':'NCM','project_id':'proj-B'},'op':{'evidence_kind':'financial','limit':3},'after':[]}
    result = adapter.execute(normal)
    adapter.execute({**normal,'id':'bad-op','op':{'limit':99}})
    sid = result['items'][0]['source_id']
    context.revoked.add(sid)
    adapter.execute({'id':'revoked','app':'internal_mock','api':'read_document',
                     'rp':{'document_id':sid},'op':{},'after':['normal']})
    context.classification = 'RESTRICTED'
    adapter.execute({'id':'restricted','app':'openalex','api':'search_works',
                     'rp':{'query':'NCM'},'op':{},'after':[]})
    return {'synthetic':True,'trace':adapter.trace,'scorer_inputs':adapter.scorer_inputs()}


if __name__ == '__main__':
    print(json.dumps(demo(),ensure_ascii=False,indent=2))
