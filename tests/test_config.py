import os

from computer_use_mcp.config import ServerConfig


def test_config_from_env_parses_limits(monkeypatch):
    monkeypatch.setenv("COMPUTER_USE_MAX_ACTIONS", "9")
    monkeypatch.setenv("COMPUTER_USE_MAX_TYPE_CHARS", "123")
    monkeypatch.setenv("COMPUTER_USE_HUMAN_OVERRIDE", "false")
    config = ServerConfig.from_env()
    assert config.max_actions_per_call == 9
    assert config.max_type_chars == 123
    assert config.human_override_enabled is False


def test_blocked_hotkeys_overrides_default(monkeypatch):
    monkeypatch.setenv("COMPUTER_USE_BLOCKED_HOTKEYS", "cmd+q, ctrl+shift+p")
    config = ServerConfig.from_env()
    assert config.blocked_hotkeys == frozenset({"CMD+Q", "CTRL+SHIFT+P"})
