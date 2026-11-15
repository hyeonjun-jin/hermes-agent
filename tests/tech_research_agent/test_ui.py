"""Streamlit functional flow; no model evaluation."""
from pathlib import Path
import pytest
from tech_research_agent.application import ResearchApplication

AppTest=pytest.importorskip('streamlit.testing.v1').AppTest


def test_ui_request_details_and_identity_isolation(tmp_path,monkeypatch):
    monkeypatch.setattr(ResearchApplication,'__init__',_initializer(tmp_path))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[2]/'tech_research_agent/ui.py')).run()
    assert not app.exception
    app.chat_input[0].set_value('수소환원제철 비교 조사').run(timeout=60)
    assert not app.exception
    assert any('SYNTHETIC' in m.value for m in app.markdown)
    assert any(e.label=='정보원·검색 조건·실행 결과' for e in app.expander)
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
