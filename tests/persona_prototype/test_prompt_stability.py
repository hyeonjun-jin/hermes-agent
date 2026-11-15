"""Business sessions must not adopt incidental host coding/toolchain state."""
import subprocess

from agent.runtime_cwd import reset_session_cwd, set_session_cwd
from persona_prototype.app import ChatApplication
from persona_prototype.mock_llm import mock_endpoint
from persona_prototype.web_mock import web_respond
from persona_prototype.web_sessions import ChatSessions
from tests.persona_prototype.surface_assertions import assert_stable_surface

QUESTION = '제 프로젝트 이름과 현재 진행 단계를 알려주세요'


def test_host_worktree_change_keeps_business_session_surface(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'pyproject.toml').write_text('[project]\nname = "fixture-workspace"\n', encoding='utf-8')
    subprocess.run(['git', 'init', '-q', str(workspace)], check=True)
    captured = []
    cwd_token = set_session_cwd(str(workspace))
    try:
        with mock_endpoint(web_respond, request_observer=captured.append) as url:
            sessions = ChatSessions(ChatApplication(tmp_path / 'app', base_url=url, api_key='offline',
                                                   model='persona-mock', multi_agent=True))
            session = sessions.create('alice')
            credentials = (session['session_id'], session['session_token'])
            first = sessions.ask(*credentials, QUESTION)
            (workspace / 'unrelated.txt').write_text('Host development changed; user facts did not.', encoding='utf-8')
            snapshot = sessions.ask(*credentials, '이전 조회 당시 진행 단계를 알려주세요')
            current = sessions.ask(*credentials, QUESTION)
        assert 'prototype' in first['answer'] and 'prototype' in snapshot['answer'] and 'prototype' in current['answer']
        assert snapshot['tool_calls'] == []
        assert_stable_surface(captured, tmp_path / 'worktree-surfaces.json')
    finally:
        reset_session_cwd(cwd_token)


def test_delayed_host_probe_keeps_business_session_surface(tmp_path, monkeypatch):
    from tools import env_probe
    probe = {'line': ''}
    monkeypatch.setattr(env_probe, 'warm_environment_probe_async', lambda: None)
    monkeypatch.setattr(env_probe, 'get_environment_probe_line', lambda **kwargs: probe['line'])
    captured = []
    with mock_endpoint(web_respond, request_observer=captured.append) as url:
        sessions = ChatSessions(ChatApplication(tmp_path / 'app', base_url=url, api_key='offline',
                                               model='persona-mock', multi_agent=True))
        session = sessions.create('alice')
        credentials = (session['session_id'], session['session_token'])
        first = sessions.ask(*credentials, QUESTION)
        probe['line'] = 'Python toolchain: fixture probe completed after the first turn.'
        current = sessions.ask(*credentials, QUESTION)
    assert 'prototype' in first['answer'] and 'prototype' in current['answer']
    assert_stable_surface(captured, tmp_path / 'probe-surfaces.json')


def test_custom_config_is_not_silently_overwritten(tmp_path):
    import pytest
    from persona_prototype.runtime_config import ensure_runtime_config
    config = tmp_path / 'config.yaml'
    original = 'agent:\n  api_max_retries: 99\n  coding_context: "on"\n'
    config.write_text(original, encoding='utf-8')
    with pytest.raises(ValueError, match='refusing to overwrite'):
        ensure_runtime_config(tmp_path, limited=True, multi_agent=True)
    assert config.read_text(encoding='utf-8') == original
