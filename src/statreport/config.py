"""
config.py — settings and SECURE, LOCAL API-key storage.

Design goals (so this package is safe to make public):
- The API key is NEVER hardcoded and NEVER stored inside the repo.
- It lives in the user's home config dir: ~/.statreport/config.json (chmod 600).
- It can be set, viewed (masked), and cleared entirely through the GUI.
- Resolution order: GUI-saved file  ->  GEMINI_API_KEY env var  ->  none.

This module is a near-verbatim sibling of EditMyRaw's config.py — same key
handling, same resolution order — only the names differ.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

CONFIG_DIR = Path(os.path.expanduser("~/.statreport"))
CONFIG_FILE = CONFIG_DIR / "config.json"

# Gemini is used "for the example" — model-agnostic in spirit, configurable below.
DEFAULT_MODEL = "gemini-2.5-flash"          # builds the report recipe (structure)
DEFAULT_NARRATIVE_MODEL = "gemini-2.5-pro"  # writes the prose around verified numbers


# ---------------------------------------------------------------------------
# Low-level config file
# ---------------------------------------------------------------------------

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _write_config(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_FILE, 0o600)  # owner read/write only
    except OSError:
        pass


# ---------------------------------------------------------------------------
# API key (set / get / clear / mask) — driven by the GUI
# ---------------------------------------------------------------------------

def save_api_key(key: str) -> None:
    data = load_config()
    data["gemini_api_key"] = key.strip()
    _write_config(data)


def clear_api_key() -> None:
    data = load_config()
    data.pop("gemini_api_key", None)
    _write_config(data)


def get_api_key() -> Tuple[Optional[str], str]:
    """Return (key, source). source is 'gui' (saved file), 'env', or 'none'."""
    data = load_config()
    if data.get("gemini_api_key"):
        return data["gemini_api_key"], "gui"
    env = os.environ.get("GEMINI_API_KEY")
    if env:
        return env, "env"
    return None, "none"


def mask_key(key: Optional[str]) -> str:
    """Show only enough to recognize the key: 'AIza…5w15' style."""
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}…{key[-4:]}"


def set_model(model: Optional[str] = None, narrative_model: Optional[str] = None) -> None:
    data = load_config()
    if model:
        data["gemini_model"] = model
    if narrative_model:
        data["gemini_narrative_model"] = narrative_model
    _write_config(data)


# ---------------------------------------------------------------------------
# Settings bundle used by the rest of the app
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Settings:
    api_key: Optional[str]
    key_source: str
    model: str = DEFAULT_MODEL
    narrative_model: str = DEFAULT_NARRATIVE_MODEL
    max_sample_rows: int = 20  # how many example rows are ever shown to the model


def load_settings() -> Settings:
    data = load_config()
    key, source = get_api_key()
    return Settings(
        api_key=key,
        key_source=source,
        model=os.environ.get("GEMINI_MODEL") or data.get("gemini_model", DEFAULT_MODEL),
        narrative_model=(os.environ.get("GEMINI_NARRATIVE_MODEL")
                         or data.get("gemini_narrative_model", DEFAULT_NARRATIVE_MODEL)),
    )


def key_status() -> dict:
    """Compact status for the GUI settings panel."""
    settings = load_settings()
    return {
        "has_key": bool(settings.api_key),
        "masked": mask_key(settings.api_key),
        "source": settings.key_source,  # gui | env | none
        "config_path": str(CONFIG_FILE),
        "model": settings.model,
        "narrative_model": settings.narrative_model,
    }
