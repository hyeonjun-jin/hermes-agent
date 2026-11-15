"""Streamlit widget execution with fixture HTTP; no backend/model network access."""
from pathlib import Path

import httpx
import pytest

from persona_prototype.data import PROFILES

AppTest = pytest.importorskip('streamlit.testing.v1', reason='Install persona_prototype UI requirements for UI tests').AppTest


@pytest.mark.parametrize('user', ['alice', 'bob', 'carol'])
def test_ui_displays_history_and_preserves_raw_while_repairing_old_tables(monkeypatch, user):
    calls = []
    def request(method, url, **kwargs):
        path = httpx.URL(url).path
        calls.append((method, path, kwargs))
        selected = httpx.URL(url).params.get('user', user)
        owner = 'bob' if 'bob-session' in path else 'carol' if 'carol-session' in path else 'alice'
        session = {'session_id': selected + '-session', 'session_token': selected + '-token'}
        raw = '| 내용 |\n|---|\n| 수율 98.2%<br>2026-11-15 [doc-42]<br/>일정 미확정 |'
        result = {'answer': raw, 'raw_answer': '모델 원응답: 98.2% [doc-42]',
                  'format_validation': {'requested': 'table', 'raw_valid': False, 'fallback_applied': True},
                  'quality': {'source_ids': ['doc-42']}}
        if path == '/health':
            value = {'model': 'offline-stub', 'mode': 'mock', 'remaining_calls': None, 'stopped': False}
        elif path == '/dev/sessions':
            value = [session]
        elif path.endswith('/resume'):
            selected = kwargs['json']['user']
            value = {'session_id': selected + '-session', 'session_token': selected + '-token'}
        elif path.endswith('/alignment'):
            value = {'revision': 1, 'preferences': {}, 'proposals': [], 'versions': [{'revision': 1}]}
        else:
            assert path == '/sessions/' + owner + '-session'
            assert kwargs['headers']['Authorization'] == 'Bearer ' + owner + '-token'
            value = {'persona': PROFILES[owner], 'turns': [{'question': owner + ' 질문', 'turn_id': owner + '-turn', 'result': result}]}
        return httpx.Response(200, json=value, request=httpx.Request(method, url))
    monkeypatch.setattr(httpx, 'request', request)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / 'persona_prototype' / 'ui.py')).run()
    if user != 'alice':
        app.sidebar.selectbox[0].select(user).run()
    assert not app.exception
    rendered = '\n'.join(m.value for m in app.markdown)
    assert '<br' not in rendered.lower()
    assert all(v in rendered for v in ['98.2%', '2026-11-15', '[doc-42]', '미확정'])
    assert app.code[0].value == '모델 원응답: 98.2% [doc-42]'
    assert app.chat_input[0].disabled is False
    assert not any(method == 'POST' and path.endswith('/messages') for method, path, _ in calls)
    assert user + ' 질문' in '\n'.join(m.value for m in app.markdown)


def test_ui_renders_evidence_warning_and_disables_exhausted_chat(monkeypatch):
    def script():
        import streamlit as st
        from persona_prototype.ui_output import render_answer
        render_answer({'answer': '- 현재 단계: prototype [environment:atlas]',
                       'raw_answer': '진행 단계 미확인',
                       'format_validation': {'requested': 'bullets', 'fallback_applied': True},
                       'evidence_validation': {'raw_review': {'issues': [{'kind': 'known_environment_as_unknown'}]}}})
        st.chat_input('질문', disabled=True)
    app = AppTest.from_function(script).run()
    assert not app.exception
    assert app.warning and app.chat_input[0].disabled
    assert app.code[0].value == '진행 단계 미확인'
    assert 'prototype' in app.markdown[0].value
