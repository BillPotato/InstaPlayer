"""Small admin-tunable runtime state: the public banner message and the
probe pause switch.

Kept in memory (single process) and mirrored to ``DATA_DIR/admin_state.json``
so it survives restarts. Writes are tiny and only happen on explicit admin
actions, so plain synchronous file IO is fine.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .config import Settings

log = logging.getLogger(__name__)

_STATE_NAME = "admin_state.json"
_MESSAGE_MAX_CHARS = 500

#: How the public banner is presented. "info" is neutral news, "warning" is
#: something users should plan around, "critical" is an outage/urgent notice.
MESSAGE_LEVELS = ("info", "warning", "critical")
_DEFAULT_LEVEL = "info"

_state: dict = {
    "message": None,        # banner shown on the public page at "/" (None = hidden)
    "messageLevel": _DEFAULT_LEVEL,
    "probesPaused": False,  # True = the periodic health probe loop skips its ticks
}


def _path(settings: Settings) -> Path:
    return settings.data_dir / _STATE_NAME


def load(settings: Settings) -> None:
    """Restore persisted state at startup. Missing/corrupt file = defaults."""
    try:
        data = json.loads(_path(settings).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except Exception:  # pragma: no cover - corrupt cache
        log.debug("Could not read admin state", exc_info=True)
        return
    if isinstance(data, dict):
        message = data.get("message")
        _state["message"] = str(message)[:_MESSAGE_MAX_CHARS] if message else None
        level = data.get("messageLevel")
        _state["messageLevel"] = level if level in MESSAGE_LEVELS else _DEFAULT_LEVEL
        _state["probesPaused"] = bool(data.get("probesPaused"))


def get() -> dict:
    return dict(_state)


def probes_paused() -> bool:
    return bool(_state["probesPaused"])


def update(settings: Settings, *, message: str | None = None,
           message_level: str | None = None,
           probes_paused: bool | None = None, clear_message: bool = False) -> dict:
    """Apply the provided fields (None = leave unchanged) and persist."""
    if clear_message:
        _state["message"] = None
        _state["messageLevel"] = _DEFAULT_LEVEL
    elif message is not None:
        text = message.strip()[:_MESSAGE_MAX_CHARS]
        _state["message"] = text or None
    if message_level in MESSAGE_LEVELS:
        _state["messageLevel"] = message_level
    if probes_paused is not None:
        _state["probesPaused"] = bool(probes_paused)
        log.info("Periodic probes %s by admin", "paused" if probes_paused else "resumed")
    try:
        path = _path(settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_state), encoding="utf-8")
    except Exception:  # pragma: no cover - advisory
        log.debug("Could not persist admin state", exc_info=True)
    return get()
