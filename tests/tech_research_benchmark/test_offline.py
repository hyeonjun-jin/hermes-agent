"""Development mutations are isolated from the eighteen evaluation cases."""
import copy
import pytest
from tech_research_benchmark.offline import DATA, load, agent_input, score, validate_all, validate_case, violations


@pytest.fixture
def fixture():
    return [load(DATA / 'development' / f) for f in ('input.json','gold.json','corpus.json')] + [load(DATA / f) for f in ('definitions.json','registry.json')]


def test_evaluation_integrity_and_gold():
    assert validate_all() == 18
    corpus, registry = load(DATA/'corpus.json'), load(DATA/'registry.json')
    for path in (DATA/'evaluation/gold').glob('*.json'):
        gold = load(path)
        case = agent_input(path.stem)
        report = score(case,gold,gold['calls'],gold['required_evidence'],corpus,registry)
        assert report['structural_success']
        assert all(report[k] == 1 for k in ('app','api','rp','op','required_evidence'))
        assert report['business_success'] is None
        assert 'calls' not in case and 'required_evidence' not in case


@pytest.mark.parametrize('mutation',['missing','duplicate','wrong_op','wrong_rp','wrong_api','no_evidence','order','security'])
def test_predictions_are_not_repaired(fixture, mutation):
    case,gold,corpus,_,registry=fixture
    calls=copy.deepcopy(gold['calls']);evidence=gold['required_evidence']
    if mutation=='missing':calls.pop()
    if mutation=='duplicate':calls.append(copy.deepcopy(calls[0]))
    if mutation=='wrong_op':calls[0]['op']['limit']=10
    if mutation=='wrong_rp':calls[0]['rp']['project_id']='proj-other'
    if mutation=='wrong_api':calls[0]['api']='upload'
    if mutation=='no_evidence':evidence=[]
    if mutation=='order':calls.reverse()
    if mutation=='security':calls[0]['app']='openalex'
    result=score(case,gold,calls,evidence,corpus,registry)
    assert not result['structural_success']
    if mutation in ('security','wrong_api','wrong_rp'):assert result['business_success'] is False
    if mutation=='duplicate':assert result['unnecessary_calls']==1


@pytest.mark.parametrize('mutation',['profile','environment','scope','span','period','precedence','forbidden'])
def test_invalid_dataset_is_rejected(fixture,mutation):
    case,gold,corpus,definitions,registry=fixture
    if mutation=='profile':case['profile']['language']='en'
    if mutation=='environment':case['environment']['audience']='other'
    if mutation=='scope':case['scope']['depth']='deep'
    if mutation=='span':gold['required_evidence'][0]['span_id']='absent'
    if mutation=='period':gold['calls'][0]['op']['to_date']='2030-01-01'
    if mutation=='precedence':gold['calls'][0]['after']=['nonexistent']
    if mutation=='forbidden':gold['forbidden']['denied_apps']=[]
    with pytest.raises((AssertionError,ValueError)):
        validate_case(case,gold,corpus,definitions,registry)


def test_development_ids_are_disjoint(fixture):
    evaluation=load(DATA/'corpus.json')
    assert not set(evaluation)&set(fixture[2])


def test_declared_sort_alternative():
    case=agent_input('H-R-E1');gold=load(DATA/'evaluation/gold/H-R-E1.json')
    calls=copy.deepcopy(gold['calls']);alt=gold['alternatives'][0]
    calls[[c['id'] for c in calls].index(alt['replace'])]=alt['call']
    assert score(case,gold,calls,gold['required_evidence'],load(DATA/'corpus.json'),load(DATA/'registry.json'))['structural_success']
