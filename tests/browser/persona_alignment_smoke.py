"""Optional local Mock browser flow: backend 8002 / UI 8503, Alice initially at fixture preferences."""
import httpx
from playwright.sync_api import sync_playwright, expect

with httpx.Client(base_url='http://127.0.0.1:8002',timeout=180) as api:
    assert api.get('/health').json()['mode']=='mock'
    session=api.post('/dev/sessions',json={'user':'alice'}).json()
    headers={'Authorization':'Bearer '+session['session_token']}
    path='/sessions/'+session['session_id']
    for i in range(4):
        q='안녕하세요' if i<3 else '현재 프로젝트 계획을 조사 분석 검증해 주세요.'
        result=api.post(path+'/messages',headers=headers,json={'message':q}).json()
        response=api.post(path+'/feedback',headers=headers,json={'turn_id':result['turn_id'],'rating':'unhelpful','consent_for_alignment':True,'preference':{'format':'table','focus':'risk'}})
        assert response.status_code==200
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1500,'height':1100})
        page.goto('http://127.0.0.1:8503',wait_until='networkidle')
        expect(page.get_by_text('현재 Mock 모드입니다.',exact=False)).to_be_visible(timeout=30000)
        page.get_by_text('답변 피드백',exact=True).last.click()
        page.get_by_text('이 선호를 Persona 후보 검증에 사용하는 데 동의합니다',exact=True).last.click()
        expect(page.get_by_role('combobox',name='선호 응답 형식',exact=True).last).to_be_visible()
        expect(page.get_by_test_id('stApp')).to_have_attribute('data-test-script-state','notRunning')
        page.get_by_role('combobox',name='선호 응답 형식',exact=True).last.fill('table')
        page.get_by_role('combobox',name='선호 응답 형식',exact=True).last.press('ArrowDown')
        page.get_by_role('combobox',name='선호 응답 형식',exact=True).last.press('Enter')
        expect(page.get_by_role('combobox',name='선호 응답 형식',exact=True).last).to_have_value('table')
        expect(page.get_by_test_id('stApp')).to_have_attribute('data-test-script-state','notRunning')
        page.get_by_role('combobox',name='선호 검색 초점',exact=True).last.fill('risk')
        page.get_by_role('combobox',name='선호 검색 초점',exact=True).last.press('ArrowDown')
        page.get_by_role('combobox',name='선호 검색 초점',exact=True).last.press('Enter')
        expect(page.get_by_role('combobox',name='선호 검색 초점',exact=True).last).to_have_value('risk')
        expect(page.get_by_test_id('stApp')).to_have_attribute('data-test-script-state','notRunning')
        page.get_by_role('button',name='피드백 저장',exact=True).last.click()
        expect(page.get_by_text('피드백을 저장했습니다. 자동 학습에는 사용하지 않습니다.',exact=True)).to_be_visible(timeout=10000)
        page.get_by_text('피드백 기반 Persona 개선',exact=True).click()
        page.get_by_role('button',name='Mock으로 후보 검증',exact=True).click()
        approve=page.get_by_role('button',name='후보 승인·적용',exact=True)
        expect(approve).to_be_visible(timeout=90000)
        expect(approve).to_be_disabled()
        page.get_by_text('Mock 검증의 한계를 확인하고 이 후보 적용을 승인합니다',exact=True).click()
        expect(approve).to_be_enabled()
        approve.click()
        expect(page.get_by_text('적용했습니다. 새 대화를 시작하면 반영됩니다.',exact=True)).to_be_visible(timeout=10000)
        expect(page.get_by_test_id('stApp')).to_have_attribute('data-test-script-state','notRunning')
        page.get_by_role('button',name='새 대화',exact=True).click()
        expect(page.get_by_test_id('stChatMessage')).to_have_count(0,timeout=30000)
        expect(page.get_by_test_id('stApp')).to_have_attribute('data-test-script-state','notRunning')
        box=page.get_by_placeholder('질문을 입력하세요')
        expect(box).to_be_visible(timeout=10000)
        box.fill('현재 프로젝트 계획을 조사 분석 검증해 주세요.');box.press('Enter')
        expect(page.get_by_text('참고 문서: doc-3',exact=False)).to_be_visible(timeout=60000)
        page.screenshot(path='/tmp/persona-alignment-browser.png',full_page=True)
        page.get_by_text('이전 선호로 롤백을 승인합니다',exact=True).click()
        page.get_by_role('button',name='롤백',exact=True).click()
        expect(page.get_by_text('롤백했습니다. 새 대화부터 반영됩니다.',exact=True)).to_be_visible(timeout=10000)
        expect(page.get_by_test_id('stApp')).to_have_attribute('data-test-script-state','notRunning')
        browser.close()
    inspector=api.post('/dev/sessions',json={'user':'alice'}).json()
    restored=api.get('/sessions/'+inspector['session_id']+'/alignment',headers={'Authorization':'Bearer '+inspector['session_token']}).json()
    assert restored['preferences']=={'format':'bullets'}
print('Mock browser alignment: consent, compare, explicit approval, new-session focus and rollback passed; paid calls 0')
