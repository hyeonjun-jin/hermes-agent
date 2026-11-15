"""Working examples through Hermes; exclusively loopback scripted Mock responses."""
import json
import tempfile
from .application import ResearchApplication, principal


def examples():
    with tempfile.TemporaryDirectory(prefix='research-demo-') as root:
        app=ResearchApplication(root)
        results=[]
        for user in ('researcher','strategy','finance'):
            result=app.ask(principal(user),user,'수소환원제철을 비교 조사해주세요.')
            results.append({'user':user,'mode':result['mode'],'complete':result['complete'],
                            'model_calls':result['model_calls'],'tools':[e['plan'] for e in result['trace']],
                            'source_ids':[s['source_id'] for s in result['evidence']]})
        return results


if __name__=='__main__':
    print(json.dumps(examples(),ensure_ascii=False,indent=2))
