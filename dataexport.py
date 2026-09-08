"""Pure helpers for turning Garmin day/activity records into CSV text.

No I/O and no network — unit-tested in ``tests/test_dataexport.py``.
"""
from __future__ import annotations

import csv
import io

WELLNESS_COLUMNS = [
    "date",
    "sleep_hours",
    "sleep_deep_hours",
    "sleep_score",
    "hrv_last_night",
    "hrv_7d_avg",
    "hrv_7d_calc",
    "hrv_status",
    "resting_hr",
    "resting_hr_7d_calc",
    "body_battery_low",
    "body_battery_high",
    "body_battery_charged",
    "body_battery_drained",
    "stress_avg",
    "spo2_avg",
    "spo2_low",
    "training_readiness",
    "training_readiness_level",
    "recovery_time_hours",
    "training_status",
    "acwr",
    "acute_load",
    "chronic_load",
    "vo2max",
]

ACTIVITY_COLUMNS = [
    "date",
    "activity_id",
    "name",
    "type",
    "distance_km",
    "duration_min",
    "avg_hr",
    "max_hr",
    "training_load",
    "aerobic_te",
    "calories",
]


def rolling(series: list, window: int) -> list:
    """Trailing mean over ``window`` points; None until at least 2 are present."""
    out: list = []
    buf: list[float] = []
    for v in series:
        if isinstance(v, (int, float)):
            buf.append(float(v))
        if len(buf) > window:
            buf.pop(0)
        out.append(round(sum(buf) / len(buf), 1) if len(buf) >= 2 else None)
    return out


def _to_csv(rows: list[dict], columns: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c) for c in columns})
    return buf.getvalue()


def build_wellness_csv(records: list[dict]) -> str:
    """One row per day, sorted ascending, with self-computed 7-day averages."""
    rows = sorted((dict(r) for r in records), key=lambda r: r.get("date") or "")
    hrv_roll = rolling([r.get("hrv_last_night") for r in rows], 7)
    rhr_roll = rolling([r.get("resting_hr") for r in rows], 7)
    for r, h, rh in zip(rows, hrv_roll, rhr_roll):
        r["hrv_7d_calc"] = h
        r["resting_hr_7d_calc"] = rh
    return _to_csv(rows, WELLNESS_COLUMNS)


def build_activities_csv(rows: list[dict]) -> str:
    """One row per activity, newest first."""
    ordered = sorted(
        (dict(r) for r in rows), key=lambda r: r.get("date") or "", reverse=True
    )
    return _to_csv(ordered, ACTIVITY_COLUMNS)
