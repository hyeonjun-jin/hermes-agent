"""Hermes settings for a business chatbot, not a host coding assistant."""

_LIMITS = '  api_max_retries: 1\n  auto_recovery_cycles: 0\n'
_DELEGATION = ('delegation:\n  max_iterations: 2\n  max_spawn_depth: 1\n'
               '  oneshot_max_children: 3\n  max_concurrent_children: 1\n'
               '  child_timeout_seconds: 45\n  inherit_mcp_toolsets: false\n')


def ensure_runtime_config(home, *, limited, multi_agent):
    limits = _LIMITS if limited else ''
    delegation = _DELEGATION if multi_agent else ''
    legacy = 'agent:\n' + limits + delegation if limited else None
    # These existing Hermes gates exclude host Git/probe data. Business Environment
    # remains an authorized tool observation, and every call limit is kept verbatim.
    settings = ('agent:\n' + limits + '  coding_context: "off"\n  environment_probe: false\n' + delegation)
    config = home / 'config.yaml'
    if config.exists():
        current = config.read_text(encoding='utf-8')
        if current == settings:
            return
        if current != legacy:
            raise ValueError('Existing profile configuration differs; refusing to overwrite')
    config.write_text(settings, encoding='utf-8')
