"""Garmin Connect data layer (isolated).

Uses the unofficial ``garminconnect`` library. Everything Garmin-specific
lives here; the rest of the app only ever sees the normalized dicts returned
by the public methods. Moving to the official Garmin Health API later means
reimplementing this one module and nothing else.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Any

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

import config

log = logging.getLogger(__name__)
SEC_PER_HOUR = 3600.0

# Garmin's numeric trainingStatus enum -> readable label.
_TRAINING_STATUS = {
    0: "none", 1: "detraining", 2: "unproductive", 3: "maintaining",
    4: "productive", 5: "recovery", 6: "overreaching", 7: "peaking", 8: "strained",
}


def _safe(fn, *args, **kwargs):
    """Call a Garmin endpoint; return None on shape/parse failures.

    Transient network / rate-limit errors are re-raised so the caller can show
    a real message instead of a silently empty dashboard.
    """
    try:
        return fn(*args, **kwargs)
    except (GarminConnectConnectionError, GarminConnectTooManyRequestsError):
        raise
    except Exception as e:  # noqa: BLE001 - defensive on purpose; payloads vary
        log.warning("garmin call %s failed: %s", getattr(fn, "__name__", fn), e)
        return None


def _dig(obj: Any, *path, default=None):
    """Walk nested dict/list by keys/indices, tolerating missing links."""
    cur = obj
    for key in path:
        if isinstance(cur, dict):
            cur = cur.get(key)
        elif isinstance(cur, (list, tuple)) and isinstance(key, int) and -len(cur) <= key < len(cur):
            cur = cur[key]
        else:
            return default
        if cur is None:
            return default
    return cur


class GarminData:
    """Thin, defensive wrapper around ``garminconnect.Garmin``."""

    def __init__(self, email: str | None = None, password: str | None = None):
        self.email = email or config.GARMIN_EMAIL
        self.password = password or config.GARMIN_PASSWORD
        self.tokenstore = config.TOKENSTORE
        self._api: Garmin | None = None
        self._mfa_state = None

    # ---- authentication --------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._api is not None

    def try_resume(self) -> bool:
        """Reconnect from a cached token store, no password needed."""
        if not os.path.isdir(self.tokenstore):
            return False
        try:
            api = Garmin()
            api.login(self.tokenstore)
            self._api = api
            self._ensure_display_name()
            log.info("resumed Garmin session from token store")
            return True
        except Exception as e:  # noqa: BLE001
            log.info("token resume failed: %s", e)
            return False

    def begin_login(self, email: str, password: str) -> str:
        """Start a fresh login. Returns 'ok' or 'mfa' (a code is required next)."""
        self.email, self.password = email, password
        api = Garmin(email=email, password=password, return_on_mfa=True)
        result = api.login()
        if isinstance(result, tuple) and result and result[0] == "needs_mfa":
            self._api = api
            self._mfa_state = result[1]
            return "mfa"
        self._api = api
        self._ensure_display_name()
        self._persist_tokens()
        return "ok"

    def complete_mfa(self, code: str) -> None:
        if not self._api or self._mfa_state is None:
            raise RuntimeError("no pending MFA login")
        self._api.resume_login(self._mfa_state, code.strip())
        self._mfa_state = None
        self._ensure_display_name()
        self._persist_tokens()

    def connect_interactive(self, ask=input) -> None:
        """Connect from a terminal: resume a cached session, else prompt.

        ``ask`` is the input function (overridable in tests). Prompts for the
        e-mail only if it isn't in config/secrets, for the password only if a
        fresh login is actually needed, and for an MFA code only if Garmin asks.
        """
        if self.try_resume():
            return
        email = self.email or ask("Garmin e-mail: ").strip()
        password = self.password
        if not password:
            try:
                from getpass import getpass

                password = getpass("Garmin password: ")
            except Exception:  # noqa: BLE001 - no tty
                password = ask("Garmin password: ")
        api = Garmin(
            email=email,
            password=password,
            prompt_mfa=lambda: ask("Enter the MFA code Garmin e-mailed you: ").strip(),
        )
        api.login(self.tokenstore)  # loads if present (ignored on first run), then dumps
        self._api = api
        self.email, self.password = email, password
        self._ensure_display_name()
        self._persist_tokens()

    def _ensure_display_name(self) -> None:
        """Guarantee ``api.display_name`` is populated.

        Several data endpoints put the profile displayName in the URL path. Some
        accounts return an empty one from ``/userprofile-service/socialProfile``
        (public profile disabled, fresh account). Recover from the profile's
        other id fields, then from the configured override, so those endpoints
        don't get ``None`` interpolated into the URL and 403.
        """
        api = self._api
        if getattr(api, "display_name", None):
            return
        prof = _safe(api.client.connectapi, "/userprofile-service/socialProfile")
        if isinstance(prof, dict):
            for key in ("displayName", "userName", "profileId"):
                val = prof.get(key)
                if val:
                    api.display_name = str(val)
                    log.info("recovered Garmin display_name from '%s'", key)
                    return
        if config.GARMIN_DISPLAY_NAME:
            api.display_name = config.GARMIN_DISPLAY_NAME
            log.info("using configured GARMIN_DISPLAY_NAME")

    def _persist_tokens(self) -> None:
        try:
            os.makedirs(self.tokenstore, exist_ok=True)
            # garminconnect exposes the underlying garth client as ``.client``;
            # ``dump(path)`` writes the OAuth token files into that directory.
            self._api.client.dump(self.tokenstore)
        except Exception as e:  # noqa: BLE001
            log.warning("could not persist Garmin tokens: %s", e)

    def _require(self) -> Garmin:
        if not self._api:
            raise RuntimeError("Garmin not connected")
        return self._api

    # ---- data ----------------------------------------------------------

    @staticmethod
    def _d(date: dt.date | str | None) -> str:
        if date is None:
            date = dt.date.today()
        if isinstance(date, dt.date):
            return date.isoformat()
        return str(date)[:10]

    def wellness_snapshot(self, date=None) -> dict:
        """``daily_record`` plus the 7-day resting-HR baseline (extra API calls)."""
        d = self._d(date)
        snap = self.daily_record(d)
        rhr_hist = [row.get("resting_hr") for row in self.history(days=8, end=d)[:-1]]
        rhr_vals = [v for v in rhr_hist if isinstance(v, (int, float))]
        snap["resting_hr_7d_avg"] = round(sum(rhr_vals) / len(rhr_vals), 1) if rhr_vals else None
        return snap

    def daily_record(self, date=None) -> dict:
        """Normalized single-day record; any missing metric comes back as None.

        All calls are read-only GETs against Garmin Connect. Nothing is written
        back to the account.
        """
        api = self._require()
        d = self._d(date)
        snap: dict[str, Any] = {"date": d}

        sleep = _safe(api.get_sleep_data, d)
        sec = _dig(sleep, "dailySleepDTO", "sleepTimeSeconds")
        snap["sleep_hours"] = round(sec / SEC_PER_HOUR, 2) if sec else None
        snap["sleep_score"] = _dig(sleep, "dailySleepDTO", "sleepScores", "overall", "value")
        deep = _dig(sleep, "dailySleepDTO", "deepSleepSeconds")
        snap["sleep_deep_hours"] = round(deep / SEC_PER_HOUR, 2) if deep else None

        hrv = _safe(api.get_hrv_data, d)
        snap["hrv_last_night"] = _dig(hrv, "hrvSummary", "lastNightAvg")
        snap["hrv_7d_avg"] = _dig(hrv, "hrvSummary", "weeklyAvg")
        status = _dig(hrv, "hrvSummary", "status")
        snap["hrv_status"] = status.lower() if isinstance(status, str) else None

        bb = _safe(api.get_body_battery, d, d)
        day0 = bb[0] if isinstance(bb, list) and bb else (bb if isinstance(bb, dict) else {})
        # The values array columns are self-described; the level is usually at
        # index 1 ([timestamp, level]) but some payloads add a status column.
        lvl_idx = 1
        for item in day0.get("bodyBatteryValueDescriptorDTOList") or []:
            if isinstance(item, dict) and item.get("bodyBatteryValueDescriptorKey") == "bodyBatteryLevel":
                lvl_idx = item.get("bodyBatteryValueDescriptorIndex", 1)
        pairs = [
            (r[0], r[lvl_idx]) for r in (day0.get("bodyBatteryValuesArray") or [])
            if isinstance(r, list) and len(r) > lvl_idx and isinstance(r[lvl_idx], (int, float))
        ]
        pairs.sort(key=lambda p: p[0])
        levels = [p[1] for p in pairs]
        snap["body_battery_now"] = levels[-1] if levels else None
        snap["body_battery_high"] = max(levels) if levels else None
        snap["body_battery_low"] = min(levels) if levels else None
        snap["body_battery_charged"] = day0.get("charged")
        snap["body_battery_drained"] = day0.get("drained")

        stress = _safe(api.get_stress_data, d)
        snap["stress_avg"] = _dig(stress, "avgStressLevel")

        spo2 = _safe(api.get_spo2_data, d)
        snap["spo2_avg"] = _dig(spo2, "averageSpO2")
        snap["spo2_low"] = _dig(spo2, "lowestSpO2")

        rhr = _safe(api.get_rhr_day, d)
        snap["resting_hr"] = _dig(
            rhr, "allMetrics", "metricsMap", "WELLNESS_RESTING_HEART_RATE", 0, "value"
        )

        tr = _safe(api.get_training_readiness, d)
        if isinstance(tr, list) and tr and isinstance(tr[0], dict):
            snap["training_readiness"] = tr[0].get("score")
            snap["training_readiness_level"] = tr[0].get("level")
            rec = tr[0].get("recoveryTime")  # minutes
            if isinstance(rec, (int, float)):
                snap["recovery_time_hours"] = round(rec / 60, 1)
        else:
            snap["training_readiness"] = None

        ts = _safe(api.get_training_status, d)
        dev_map = _dig(ts, "mostRecentTrainingStatus", "latestTrainingStatusData", default={}) or {}
        first = next(iter(dev_map.values()), {}) if isinstance(dev_map, dict) else {}
        if isinstance(first, dict):
            snap["training_status"] = _TRAINING_STATUS.get(first.get("trainingStatus"))
            atl = first.get("acuteTrainingLoadDTO") or {}
            snap["acwr"] = atl.get("dailyAcuteChronicWorkloadRatio")
            snap["acute_load"] = atl.get("dailyTrainingLoadAcute")
            snap["chronic_load"] = atl.get("dailyTrainingLoadChronic")
        snap["vo2max"] = (
            _dig(ts, "mostRecentVO2Max", "generic", "vo2MaxValue")
            or _dig(ts, "mostRecentVO2Max", "generic", "vo2MaxPreciseValue")
        )

        return snap

    def history(self, days: int = 14, end=None) -> list[dict]:
        """Light daily rows for the trend charts (HRV, sleep, resting HR)."""
        api = self._require()
        end_d = dt.date.today() if end is None else (
            end if isinstance(end, dt.date) else dt.date.fromisoformat(str(end)[:10])
        )
        out = []
        for i in range(days - 1, -1, -1):
            d = (end_d - dt.timedelta(days=i)).isoformat()
            hrv = _safe(api.get_hrv_data, d)
            sleep = _safe(api.get_sleep_data, d)
            rhr = _safe(api.get_rhr_day, d)
            sec = _dig(sleep, "dailySleepDTO", "sleepTimeSeconds")
            out.append({
                "date": d,
                "hrv_last_night": _dig(hrv, "hrvSummary", "lastNightAvg"),
                "hrv_7d_avg": _dig(hrv, "hrvSummary", "weeklyAvg"),
                "sleep_hours": round(sec / SEC_PER_HOUR, 2) if sec else None,
                "sleep_score": _dig(sleep, "dailySleepDTO", "sleepScores", "overall", "value"),
                "resting_hr": _dig(
                    rhr, "allMetrics", "metricsMap", "WELLNESS_RESTING_HEART_RATE", 0, "value"
                ),
            })
        return out

    def recent_activities(self, limit: int = 10) -> list[dict]:
        api = self._require()
        raw = _safe(api.get_activities, 0, limit) or []
        out = []
        for a in raw:
            if not isinstance(a, dict):
                continue
            dist_m = a.get("distance") or 0
            dur_s = a.get("duration") or 0
            out.append({
                "activity_id": a.get("activityId"),
                "date": (a.get("startTimeLocal") or "")[:10],
                "name": a.get("activityName"),
                "type": _dig(a, "activityType", "typeKey") or "",
                "distance_km": round(dist_m / 1000, 2) if dist_m else None,
                "duration_min": round(dur_s / 60, 1) if dur_s else None,
                "avg_hr": a.get("averageHR"),
                "max_hr": a.get("maxHR"),
                "training_load": a.get("activityTrainingLoad"),
                "aerobic_te": a.get("aerobicTrainingEffect"),
                "calories": a.get("calories"),
            })
        return out

    def activity_detail(self, activity_id) -> dict | None:
        return _safe(self._require().get_activity_details, activity_id)

    def last_sync_time(self) -> dt.datetime | None:
        info = _safe(self._require().get_device_last_used)
        ts = _dig(info, "lastUsedDeviceUploadTime")
        if isinstance(ts, (int, float)):
            try:
                return dt.datetime.fromtimestamp(ts / 1000)
            except (OverflowError, OSError, ValueError):
                return None
        return None


__all__ = [
    "GarminData",
    "GarminConnectAuthenticationError",
    "GarminConnectConnectionError",
    "GarminConnectTooManyRequestsError",
]
