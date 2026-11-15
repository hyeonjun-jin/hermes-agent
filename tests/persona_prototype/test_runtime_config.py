"""Upgrade only the exact generated settings and preserve the validation budget."""
import pytest

from hermes_yaml import safe_load
from persona_prototype.runtime_config import ensure_runtime_config


@pytest.mark.parametrize('multi', [False, True])
def test_legacy_generated_config_preserves_limits_on_upgrade(tmp_path, multi):
    original = 'agent:\n  api_max_retries: 1\n  auto_recovery_cycles: 0\n'
    if multi:
        original += ('delegation:\n  max_iterations: 2\n  max_spawn_depth: 1\n'
                     '  oneshot_max_children: 3\n  max_concurrent_children: 1\n'
                     '  child_timeout_seconds: 45\n  inherit_mcp_toolsets: false\n')
    config = tmp_path / 'config.yaml'
    config.write_text(original, encoding='utf-8')
    previous = safe_load(original)
    ensure_runtime_config(tmp_path, limited=True, multi_agent=multi)
    upgraded = config.read_text(encoding='utf-8')
    actual = safe_load(upgraded)
    assert actual['agent']['coding_context'] == 'off'
    assert actual['agent']['environment_probe'] is False
    assert {key: actual['agent'][key] for key in previous['agent']} == previous['agent']
    assert actual.get('delegation') == previous.get('delegation')
    ensure_runtime_config(tmp_path, limited=True, multi_agent=multi)
    assert config.read_text(encoding='utf-8') == upgraded
