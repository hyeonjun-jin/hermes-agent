"""Streamlit functional flow; no model evaluation."""
from pathlib import Path
import pytest
from tech_research_agent.application import ResearchApplication

AppTest=pytest.importorskip('streamlit.testing.v1').AppTest


@pytest.fixture(autouse=True)
def isolate_streamlit_resources():
    import streamlit as st
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


def test_ui_request_details_and_identity_isolation(tmp_path,monkeypatch):
    monkeypatch.setattr(ResearchApplication,'__init__',_initializer(tmp_path))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[2]/'tech_research_agent/ui.py')).run()
    assert not app.exception
    app.chat_input[0].set_value('수소환원제철 비교 조사').run(timeout=60)
    assert not app.exception
    assert any('SYNTHETIC' in m.value for m in app.markdown)
    assert any(e.label=='정보원·검색 조건·실행 결과' for e in app.expander)
    assert any(e.label=='현재 Profile' for e in app.sidebar.expander)
    assert any(e.label=='Environment · 정보 자원' for e in app.expander)
    assert any(e.label=='Evidence · Tool Calling으로 확보한 자료' for e in app.expander)
    resources=next(t.value for t in app.table if '연결 확인' in t.value.columns)
    assert all('미확인' in value for value in resources['연결 확인'])
    evidence=next(t.value for t in app.table if '문서 ID' in t.value.columns)
    assert all(value=='SYNTHETIC' for value in evidence['자료 구분'])
    assert all('research-tool-' in value for value in evidence['조회 근거'])
    app.sidebar.selectbox[0].select('finance').run()
    assert not app.exception
    assert not app.chat_message


def _initializer(root):
    original=ResearchApplication.__init__
    def initialize(self,_):
        original(self,root)
    return initialize


def test_real_ui_warns_and_remains_disabled_without_server_approval(tmp_path,monkeypatch):
    monkeypatch.setattr(ResearchApplication,'__init__',_initializer(tmp_path))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[2]/'tech_research_agent/ui.py')).run()
    app.sidebar.radio[0].set_value('real').run()
    assert not app.exception and app.chat_input[0].disabled
    assert any('실제 비용' in w.value for w in app.warning)


def test_approved_public_ui_cannot_grant_processing_rights(tmp_path,monkeypatch):
    monkeypatch.setattr(ResearchApplication,'__init__',_initializer(tmp_path))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[2]/'tech_research_agent/ui.py')).run()
    app.sidebar.radio[0].set_value('approved_public').run()
    assert not app.exception and app.chat_input[0].disabled
    app.sidebar.checkbox[0].check().run()
    assert not app.exception and app.chat_input[0].disabled
    assert any('UI 동의' in caption.value for caption in app.caption)


def test_public_connector_ui_labels_sources_and_blocks_real(tmp_path,monkeypatch):
    import httpx
    from tech_research_agent.connectors.openalex import OpenAlexConnector
    original=ResearchApplication.__init__
    sent=[]
    def send(request):
        sent.append(request)
        return httpx.Response(200,json={'results':[]})
    def initialize(self,_):
        original(self,tmp_path,source_connectors={'openalex':OpenAlexConnector(enabled=True,transport=httpx.MockTransport(send))})
    monkeypatch.setattr(ResearchApplication,'__init__',initialize)
    app=AppTest.from_file(str(Path(__file__).resolve().parents[2]/'tech_research_agent/ui.py')).run()
    assert not app.exception
    assert any('PUBLIC OpenAlex' in caption.value for caption in app.caption)
    app.chat_input[0].set_value('수소환원제철을 논문만 조사').run(timeout=60)
    assert not app.exception and len(sent)==1
    assert any('조사가 완료되지 않았습니다' in warning.value for warning in app.warning)
    app.sidebar.radio[0].set_value('real').run()
    assert not app.exception and app.chat_input[0].disabled
    assert any('반출 승인' in info.value for info in app.info)
