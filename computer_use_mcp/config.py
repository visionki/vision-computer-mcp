from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _normalize_combo(combo: str) -> str:
    parts = [part.strip().upper() for part in combo.split("+") if part.strip()]
    return "+".join(parts)


@dataclass(slots=True)
class ServerConfig:
    name: str = "Vision Computer MCP"
    max_actions_per_call: int = 0
    max_type_chars: int = 200
    default_pause_between_ms: int = 80
    mouse_interrupt_threshold_px: int = 15
    state_ttl_seconds: int = 120
    human_override_enabled: bool = True
    include_cursor_by_default: bool = True
    debug_enabled: bool = True
    debug_save_images: bool = True
    debug_dir: str = ".computer_use_mcp_debug"
    blocked_hotkeys: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "ALT+F4",
                "CTRL+ALT+DEL",
                "WIN+R",
                "CMD+Q",
            }
        )
    )
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "ServerConfig":
        blocked_raw = os.getenv("COMPUTER_USE_BLOCKED_HOTKEYS")
        blocked_hotkeys = (
            frozenset(_normalize_combo(part) for part in blocked_raw.split(",") if part.strip())
            if blocked_raw
            else cls().blocked_hotkeys
        )
        return cls(
            max_actions_per_call=max(0, _env_int("COMPUTER_USE_MAX_ACTIONS", 0)),
            max_type_chars=max(1, _env_int("COMPUTER_USE_MAX_TYPE_CHARS", 200)),
            default_pause_between_ms=max(0, _env_int("COMPUTER_USE_DEFAULT_PAUSE_MS", 80)),
            mouse_interrupt_threshold_px=max(
                1, _env_int("COMPUTER_USE_MOUSE_INTERRUPT_THRESHOLD_PX", 15)
            ),
            state_ttl_seconds=max(10, _env_int("COMPUTER_USE_STATE_TTL_SECONDS", 120)),
            human_override_enabled=_env_bool("COMPUTER_USE_HUMAN_OVERRIDE", True),
            include_cursor_by_default=_env_bool("COMPUTER_USE_INCLUDE_CURSOR", True),
            debug_enabled=_env_bool("COMPUTER_USE_DEBUG", True),
            debug_save_images=_env_bool("COMPUTER_USE_DEBUG_SAVE_IMAGES", True),
            debug_dir=os.getenv("COMPUTER_USE_DEBUG_DIR", ".computer_use_mcp_debug"),
            blocked_hotkeys=blocked_hotkeys,
            log_level=os.getenv("COMPUTER_USE_LOG_LEVEL", "INFO").upper(),
        )
