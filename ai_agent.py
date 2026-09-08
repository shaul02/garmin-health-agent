"""Pluggable AI brain.

Backends: rules | gemini | claude | openai | ollama. Every backend exposes
``brief(snapshot, history, activities)`` and
``ask(question, snapshot, history, activities)`` and returns Markdown text.

The ``rules`` backend needs no API key — it composes an answer from
``analysis.py`` — so the app is always useful.
"""
from __future__ import annotations

import config
from analysis import sleep_debt, training_readiness_verdict, trend, weekly_load

DISCLAIMER = (
    "\n\n---\n_המלצות כלליות לכושר בלבד, לא ייעוץ רפואי. "
    "אם יש תסמינים חריגים או מתמשכים — פנה/י לרופא._"
)

SYSTEM_PROMPT = (
    "אתה סוכן בריאות ומאמן כושר אישי. אתה מקבל נתוני Garmin יומיים "
    "(שינה, HRV, Body Battery, סטרס, דופק מנוחה, מוכנוּת לאימון, אימונים אחרונים). "
    "תפקידך לתת המלצה קונקרטית וברורה מה לעשות היום מבחינת אימון והתאוששות.\n"
    "כללים: השב בעברית, קצר וישיר (עד ~120 מילים אלא אם ביקשו יותר). "
    "התבסס אך ורק על הנתונים שקיבלת; אם חסר נתון מהותי — אמור זאת במפורש. "
    "אל תיתן אבחנות רפואיות. כשאפשר, ציין טווח מאמץ מומלץ (זון דופק או תחושה)."
)


def _context_text(snapshot: dict, history: list[dict], activities: list[dict]) -> str:
    v = training_readiness_verdict(snapshot, config.SLEEP_TARGET_HOURS)
    hrv_series = [h.get("hrv_last_night") for h in history if h.get("hrv_last_night")]
    sleep_series = [h.get("sleep_hours") for h in history if h.get("sleep_hours")]
    load = weekly_load(activities)
    lines = [
        f"תאריך: {snapshot.get('date', '—')}",
        f"מוכנוּת מחושבת: {v.score}/100 ({v.level}). גורמים: " + "; ".join(v.reasons),
        f"HRV אתמול: {snapshot.get('hrv_last_night', '—')} ms "
        f"(ממוצע 7 ימים: {snapshot.get('hrv_7d_avg', '—')}, מגמה: {trend(hrv_series)})",
        f"שינה: {snapshot.get('sleep_hours', '—')} שעות, ציון {snapshot.get('sleep_score', '—')}, "
        f"חוב שינה מצטבר: {sleep_debt(sleep_series, config.SLEEP_TARGET_HOURS)} שעות",
        f"Body Battery: כעת {snapshot.get('body_battery_now', '—')}, "
        f"טווח היום {snapshot.get('body_battery_low', '—')}–{snapshot.get('body_battery_high', '—')}",
        f"סטרס ממוצע: {snapshot.get('stress_avg', '—')}",
        f"דופק מנוחה: {snapshot.get('resting_hr', '—')} "
        f"(ממוצע 7 ימים: {snapshot.get('resting_hr_7d_avg', '—')})",
        f"Training Status: {snapshot.get('training_status', '—')}, "
        f"VO2max: {snapshot.get('vo2max', '—')}",
        f"עומס אימונים: 7 ימים אחרונים {load['this_week']}, 7 שלפניהם {load['prev_week']}, "
        f"יחס {load['ratio']}" + (f" — {load['flag']}" if load["flag"] else ""),
    ]
    if activities:
        lines.append("אימונים אחרונים:")
        for a in activities[:5]:
            lines.append(
                f"  • {a.get('date', '—')} {a.get('type', '')} "
                f"{a.get('distance_km', '—')} ק\"מ / {a.get('duration_min', '—')} דק' / "
                f"דופק ממוצע {a.get('avg_hr', '—')} / עומס {a.get('training_load', '—')}"
            )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Offline rule-based backend
# --------------------------------------------------------------------------
class RulesBackend:
    provider = "rules"
    init_error: str | None = None

    _REC = {
        "hard": "מתאים לאימון איכות: אינטרוולים / טמפו / כוח כבד.",
        "moderate": "אימון בעצימות בינונית: ריצה רציפה קלה־בינונית, זון 2–3.",
        "easy": "רק אימון קל: הליכה, ריצה קלה בזון 2, ניידות.",
        "rest": "יום מנוחה או התאוששות אקטיבית בלבד.",
    }

    def brief(self, snapshot, history, activities):
        v = training_readiness_verdict(snapshot, config.SLEEP_TARGET_HOURS)
        hrv_series = [h.get("hrv_last_night") for h in history if h.get("hrv_last_night")]
        sleep_series = [h.get("sleep_hours") for h in history if h.get("sleep_hours")]
        load = weekly_load(activities)

        out = [f"**{v.headline}**", ""]
        out += [f"- {r}" for r in v.reasons]

        hrv_tr = trend(hrv_series)
        if hrv_tr == "falling":
            out.append("- מגמת HRV יורדת בימים האחרונים — שים לב לעומס מצטבר.")
        elif hrv_tr == "rising":
            out.append("- מגמת HRV עולה — סימן טוב להתאוששות.")

        debt = sleep_debt(sleep_series, config.SLEEP_TARGET_HOURS)
        if debt >= 3:
            out.append(f"- חוב שינה מצטבר של {debt} שעות — כדאי להשלים לפני אימון מפתח.")
        if load["flag"]:
            out.append(f"- {load['flag']}.")

        out += ["", f"**המלצה:** {self._REC[v.level]}"]
        return "\n".join(out) + DISCLAIMER

    def ask(self, question, snapshot, history, activities):
        q = question.strip()
        low = q.lower()
        v = training_readiness_verdict(snapshot, config.SLEEP_TARGET_HOURS)

        if any(w in q for w in ("לרוץ", "אימון", "להתאמן", "כדאי", "לעשות")) or "train" in low:
            return self.brief(snapshot, history, activities)
        if "שינה" in q or "sleep" in low:
            sl = [h.get("sleep_hours") for h in history if h.get("sleep_hours")]
            return (
                f"שינה אתמול: {snapshot.get('sleep_hours', '—')} שעות "
                f"(ציון {snapshot.get('sleep_score', '—')}). "
                f"מגמת 7 ימים: {trend(sl)}. "
                f"חוב מצטבר: {sleep_debt(sl, config.SLEEP_TARGET_HOURS)} שעות." + DISCLAIMER
            )
        if "hrv" in low or "לב" in q or "דופק" in q:
            hs = [h.get("hrv_last_night") for h in history if h.get("hrv_last_night")]
            return (
                f"HRV אתמול: {snapshot.get('hrv_last_night', '—')} ms, "
                f"ממוצע 7 ימים {snapshot.get('hrv_7d_avg', '—')}, מגמה {trend(hs)}. "
                f"דופק מנוחה: {snapshot.get('resting_hr', '—')} "
                f"(ממוצע {snapshot.get('resting_hr_7d_avg', '—')})." + DISCLAIMER
            )
        return (
            "במצב ללא מנוע AI אני עונה על שאלות אימון / שינה / HRV. "
            f"סיכום מהיר: {v.headline}." + DISCLAIMER
        )


# --------------------------------------------------------------------------
# Real LLM backends
# --------------------------------------------------------------------------
class _LLMBackend:
    provider = "llm"
    init_error: str | None = None

    def _complete(self, system: str, user: str) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def brief(self, snapshot, history, activities):
        ctx = _context_text(snapshot, history, activities)
        user = (
            "להלן נתוני היום. תן סיכום בוקר קצר: מצב ההתאוששות, 1–2 דגשים, "
            "והמלצת אימון קונקרטית להיום.\n\n" + ctx
        )
        return self._complete(SYSTEM_PROMPT, user) + DISCLAIMER

    def ask(self, question, snapshot, history, activities):
        ctx = _context_text(snapshot, history, activities)
        user = f"שאלה: {question}\n\nנתונים עדכניים:\n{ctx}"
        return self._complete(SYSTEM_PROMPT, user) + DISCLAIMER


class GeminiBackend(_LLMBackend):
    provider = "gemini"

    def __init__(self):
        from google import genai

        self._genai = genai
        self._client = genai.Client(api_key=config.GEMINI_API_KEY)

    def _complete(self, system, user):
        from google.genai import types

        resp = self._client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.4,
                max_output_tokens=800,
            ),
        )
        return (resp.text or "").strip()


class ClaudeBackend(_LLMBackend):
    provider = "claude"

    def __init__(self):
        import anthropic

        self._client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def _complete(self, system, user):
        msg = self._client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=1000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in msg.content if b.type == "text").strip()


class OpenAIBackend(_LLMBackend):
    provider = "openai"

    def __init__(self):
        from openai import OpenAI

        self._client = OpenAI(api_key=config.OPENAI_API_KEY)

    def _complete(self, system, user):
        r = self._client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.4,
            max_tokens=800,
        )
        return (r.choices[0].message.content or "").strip()


class OllamaBackend(_LLMBackend):
    provider = "ollama"

    def _complete(self, system, user):
        import requests

        r = requests.post(
            f"{config.OLLAMA_HOST}/api/chat",
            json={
                "model": config.OLLAMA_MODEL,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["message"]["content"].strip()


_BACKENDS = {
    "rules": RulesBackend,
    "gemini": GeminiBackend,
    "claude": ClaudeBackend,
    "openai": OpenAIBackend,
    "ollama": OllamaBackend,
}


def get_agent(provider: str | None = None):
    """Return a backend instance, falling back to ``rules`` on any failure."""
    name = (provider or config.effective_provider()).lower()
    cls = _BACKENDS.get(name, RulesBackend)
    try:
        return cls()
    except Exception as e:  # noqa: BLE001 - missing lib, bad key, etc.
        fallback = RulesBackend()
        fallback.init_error = f"{name}: {e}"
        return fallback
