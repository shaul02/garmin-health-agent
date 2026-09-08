"""Pure analysis functions — no I/O, no external services, fully unit-tested.

This module is the rule-based core of the agent. It also powers the offline
("rules") AI backend, so the app stays useful with zero API keys.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from statistics import mean

_LEVEL_HE = {
    "rest": "מנוחה",
    "easy": "אימון קל",
    "moderate": "אימון בינוני",
    "hard": "אימון עצים",
}


@dataclass
class Verdict:
    level: str  # "rest" | "easy" | "moderate" | "hard"
    score: int  # 0-100 composite readiness
    headline: str  # Hebrew one-liner
    reasons: list[str] = field(default_factory=list)


def _level_for_score(score: int) -> str:
    if score >= 75:
        return "hard"
    if score >= 55:
        return "moderate"
    if score >= 35:
        return "easy"
    return "rest"


def training_readiness_verdict(s: dict, sleep_target: float = 7.5) -> Verdict:
    """Decide how hard to train today.

    If Garmin's own Training Readiness score is present we anchor on it and
    surface the label. Otherwise we build a composite from HRV vs the personal
    7-day baseline, sleep, Body Battery, resting HR and stress.
    """
    reasons: list[str] = []
    garmin_score = s.get("training_readiness")

    if isinstance(garmin_score, (int, float)):
        score = int(round(garmin_score))
        lvl = s.get("training_readiness_level")
        reasons.append(f"Garmin Training Readiness: {score}/100" + (f" ({lvl})" if lvl else ""))
        rec = s.get("recovery_time_hours")
        if isinstance(rec, (int, float)) and rec > 24:
            reasons.append(f"Garmin ממליץ עוד {rec:.0f} שעות התאוששות")
    else:
        score = 100

        hrv, hrv_avg = s.get("hrv_last_night"), s.get("hrv_7d_avg")
        if hrv and hrv_avg:
            ratio = hrv / hrv_avg
            if ratio < 0.8:
                score -= 35
                reasons.append(f"HRV נמוך משמעותית מהממוצע ({hrv:.0f} מול {hrv_avg:.0f} ms)")
            elif ratio < 0.9:
                score -= 20
                reasons.append(f"HRV מתחת לממוצע ({hrv:.0f} מול {hrv_avg:.0f} ms)")
            elif ratio > 1.05:
                score += 5
                reasons.append(f"HRV מעל הממוצע ({hrv:.0f} מול {hrv_avg:.0f} ms)")

        sleep_h = s.get("sleep_hours")
        if sleep_h is not None:
            if sleep_h < 6:
                score -= 20
                reasons.append(f"שינה קצרה ({sleep_h:.1f} שעות)")
            elif sleep_h < 7:
                score -= 8
                reasons.append(f"שינה מתחת ליעד ({sleep_h:.1f} שעות)")
            elif sleep_h >= sleep_target:
                score += 5
                reasons.append(f"שינה טובה ({sleep_h:.1f} שעות)")

        sc = s.get("sleep_score")
        if isinstance(sc, (int, float)) and sc < 50:
            score -= 10
            reasons.append(f"ציון שינה נמוך ({sc})")

        bb = s.get("body_battery_now")
        if bb is not None:
            if bb < 30:
                score -= 20
                reasons.append(f"Body Battery נמוך ({bb})")
            elif bb < 50:
                score -= 10
                reasons.append(f"Body Battery בינוני ({bb})")
            elif bb > 70:
                score += 5
                reasons.append(f"Body Battery גבוה ({bb})")

        rhr, rhr_avg = s.get("resting_hr"), s.get("resting_hr_7d_avg")
        if rhr and rhr_avg:
            delta = rhr - rhr_avg
            if delta >= 5:
                score -= 15
                reasons.append(f"דופק מנוחה גבוה ב-{delta:.0f} פעימות מהממוצע")
            elif delta >= 3:
                score -= 8
                reasons.append(f"דופק מנוחה מעט גבוה (+{delta:.0f})")

        stress = s.get("stress_avg")
        if isinstance(stress, (int, float)) and stress > 60:
            score -= 10
            reasons.append(f"רמת סטרס ממוצעת גבוהה ({stress})")

        # No signal at all -> don't confidently claim a hard day.
        if not reasons:
            score = min(score, 60)

    score = max(0, min(100, score))
    level = _level_for_score(score)
    headline = f"{_LEVEL_HE[level]} · מוכנות {score}/100"
    if not reasons:
        reasons.append("אין מספיק נתונים להסבר מפורט — הערכה בסיסית בלבד")
    return Verdict(level=level, score=score, headline=headline, reasons=reasons)


def trend(values: list, eps: float = 0.01) -> str:
    """Direction of a short series: 'rising' | 'falling' | 'stable' | 'unknown'.

    ``eps`` is the per-step slope threshold as a fraction of the series mean.
    """
    clean = [v for v in values if isinstance(v, (int, float))]
    if len(clean) < 3:
        return "unknown"
    xs = list(range(len(clean)))
    mx, my = mean(xs), mean(clean)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0 or my == 0:
        return "stable"
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, clean)) / denom
    norm = slope / abs(my)
    if norm > eps:
        return "rising"
    if norm < -eps:
        return "falling"
    return "stable"


def sleep_debt(hours_per_night: list, target: float = 7.5) -> float:
    """Accumulated sleep debt in hours over the given nights (floored at 0)."""
    debt = 0.0
    for h in hours_per_night:
        if isinstance(h, (int, float)):
            debt += target - h
    return round(max(0.0, debt), 1)


def weekly_load(activities: list[dict], now_date=None) -> dict:
    """Compare the last 7 days of training load to the 7 days before that.

    Each activity needs ``date`` (ISO string or ``date``) and optionally
    ``training_load``; falls back to ``duration_min`` when load is absent.
    """
    if now_date is None:
        now_date = dt.date.today()
    elif isinstance(now_date, str):
        now_date = dt.date.fromisoformat(now_date[:10])

    this_week = prev_week = 0.0
    for a in activities:
        d = a.get("date")
        if isinstance(d, str):
            try:
                d = dt.date.fromisoformat(d[:10])
            except ValueError:
                continue
        if not isinstance(d, dt.date):
            continue
        age = (now_date - d).days
        load = a.get("training_load")
        if not isinstance(load, (int, float)):
            load = (a.get("duration_min") or 0) * 1.0
        if 0 <= age < 7:
            this_week += load
        elif 7 <= age < 14:
            prev_week += load

    ratio = (this_week / prev_week) if prev_week > 0 else None
    flag = None
    if ratio is not None and ratio > 1.5:
        flag = "עומס האימונים ב-7 הימים האחרונים גבוה ב-50%+ מהשבוע שלפניו — היזהר מקפיצה חדה"
    elif ratio is not None and ratio < 0.5 and this_week > 0:
        flag = "ירידה חדה בעומס האימונים לעומת השבוע שלפני"
    return {
        "this_week": round(this_week, 1),
        "prev_week": round(prev_week, 1),
        "ratio": round(ratio, 2) if ratio is not None else None,
        "flag": flag,
    }
