"""Central configuration.

Values are read from Streamlit secrets first (``.streamlit/secrets.toml``),
then from environment variables, then from a hard-coded default. Both a flat
key and a ``[garmin]`` / ``[ai]`` section key are accepted.
"""
from __future__ import annotations

import os
import pathlib
import tomllib
from collections.abc import Mapping


def _deep_dict(v):
    """Recursively turn any Mapping (e.g. Streamlit's Secrets) into plain dicts."""
    if isinstance(v, Mapping):
        return {k: _deep_dict(v[k]) for k in v.keys()}
    return v


def _load_secrets() -> dict:
    """Read secrets whether we run under ``streamlit run`` or as a plain script.

    Under Streamlit, ``st.secrets`` is authoritative. From a bare CLI (sync.py),
    parse ``.streamlit/secrets.toml`` directly with the stdlib TOML reader.
    """
    try:
        import streamlit as st

        if len(st.secrets):  # raises if no secrets file — caught below
            return _deep_dict(st.secrets)
    except Exception:  # noqa: BLE001
        pass
    for p in (
        pathlib.Path(".streamlit/secrets.toml"),
        pathlib.Path.home() / ".streamlit" / "secrets.toml",
    ):
        try:
            if p.is_file():
                return tomllib.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {}


_secrets = _load_secrets()


def _get(key: str, default: str | None = None) -> str | None:
    try:
        if key in _secrets:
            return str(_secrets[key])
        for section in ("garmin", "ai"):
            sec = _secrets.get(section)
            if isinstance(sec, Mapping) and key in sec:
                return str(sec[key])
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get(key, default)


# ---- Garmin -----------------------------------------------------------------
GARMIN_EMAIL = _get("GARMIN_EMAIL")
GARMIN_PASSWORD = _get("GARMIN_PASSWORD")
# Optional: some Garmin accounts return an empty social-profile displayName
# (e.g. public profile disabled). Data endpoints need it in the URL path, so
# set it here as a fallback — it is the id in connect.garmin.com/modern/profile/<id>.
GARMIN_DISPLAY_NAME = _get("GARMIN_DISPLAY_NAME")
TOKENSTORE = os.path.expanduser(_get("GARMIN_TOKENSTORE", "~/.garmin-health-agent/tokens"))

# ---- AI brain -------------------------------------------------------------
# provider: rules | gemini | claude | openai | ollama
AI_PROVIDER = (_get("AI_PROVIDER", "gemini") or "gemini").lower()

GEMINI_API_KEY = _get("GEMINI_API_KEY") or _get("GOOGLE_API_KEY")
ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
OPENAI_API_KEY = _get("OPENAI_API_KEY")
OLLAMA_HOST = _get("OLLAMA_HOST", "http://localhost:11434")

GEMINI_MODEL = _get("GEMINI_MODEL", "gemini-2.5-flash")
CLAUDE_MODEL = _get("CLAUDE_MODEL", "claude-sonnet-5")
OPENAI_MODEL = _get("OPENAI_MODEL", "gpt-4o-mini")
OLLAMA_MODEL = _get("OLLAMA_MODEL", "llama3.1")

# ---- analysis knobs ------------------------------------------------------
SLEEP_TARGET_HOURS = float(_get("SLEEP_TARGET_HOURS", "7.5"))


def effective_provider() -> str:
    """The provider we can actually use — falls back to ``rules`` with no key."""
    p = AI_PROVIDER
    if p == "gemini" and not GEMINI_API_KEY:
        return "rules"
    if p == "claude" and not ANTHROPIC_API_KEY:
        return "rules"
    if p == "openai" and not OPENAI_API_KEY:
        return "rules"
    return p
