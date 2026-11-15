"""Execution progress, not model quality evaluation."""

def progress(stages, trace, audit):
    completed=[s['role'] for s in stages if not s['error']]
    failed=next((s['role'] for s in stages if s['error']),None)
    pending=[r for r in ('research','analysis','verification') if r not in completed]
    calls={r:0 for r in ('research','analysis','verification')}
    for event in audit:
        if event.get('reserved_attempt',isinstance(event.get('status'),int) and not event.get('budget_blocked')):
            calls[event['role']]+=1
    successful=[e for e in trace if e['executed'] and e['result']['status']=='ok']
    searched=any('search' in e['plan']['api'] or e['plan']['api']=='list_disclosures' for e in successful)
    read=any(e['plan']['api'].startswith('read_') for e in successful)
    acquired=searched or any(e['plan']['api']=='read_financials' for e in successful)
    verified=any(e['plan']['id'].startswith('verification-') and e['plan']['api'].startswith('read_') for e in successful)
    remaining=[]
    if not acquired:remaining.append('검색 정보원 선택 및 검색 결과 확보')
    if not read:remaining.append('문서 원문 Read')
    if 'research' in pending:remaining.append('Research 최종 응답')
    if 'analysis' in pending:remaining.append('Analysis 근거 해석·비교')
    if 'verification' in pending or not verified:remaining.append('Verification 원문 재조회·최종 확인')
    return {'completed_roles':completed,'stopped_role':failed,'pending_roles':pending,
            'calls_by_role':calls,'search_results_received':searched,'original_read':read,'verification_read':verified,
            'remaining_work':remaining,
            'stop_reason':next((e.get('block_reason') or e.get('reason') for e in reversed(audit)
                                if e.get('budget_blocked') or e.get('status')=='egress_denied'),None)}
