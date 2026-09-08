"""Central configuration.

Values are read from Streamlit secrets first (``.streamlit/secrets.toml``),
then from environment variables, then from a hard-coded default. Both a flat
key and a ``[garmin]`` / ``[ai]`` section key are accepted.
"""
from __future__ import annotations

import os

try:  # available when running under Streamlit
    import streamlit as st

    _secrets = st.secrets
except Exception:  # noqa: BLE001 - any import/runtime issue means "no secrets"
    _secrets = {}


def _get(key: str, default: str | None = None) -> str | None:
    try:
        if key in _secrets:
            return str(_secrets[key])
        for section in ("garmin", "ai"):
            if section in _secrets and key in _secrets[section]:
                return str(_secrets[section][key])
    except Exception:  # noqa: BLE001 - missing secrets file raises on access
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
