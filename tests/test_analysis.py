import datetime as dt

from analysis import sleep_debt, training_readiness_verdict, trend, weekly_load


def test_verdict_uses_garmin_score_when_present():
    v = training_readiness_verdict({"training_readiness": 82})
    assert v.level == "hard"
    assert v.score == 82
    assert any("Garmin" in r for r in v.reasons)


def test_verdict_low_recovery_composite():
    v = training_readiness_verdict({
        "hrv_last_night": 40, "hrv_7d_avg": 60,      # ratio 0.67 -> -35
        "sleep_hours": 5.0,                           # -20
        "body_battery_now": 20,                       # -20
        "resting_hr": 58, "resting_hr_7d_avg": 50,    # +8 -> -15
    })
    assert v.level == "rest"
    assert v.score <= 20


def test_verdict_good_day():
    v = training_readiness_verdict({
        "hrv_last_night": 75, "hrv_7d_avg": 70,
        "sleep_hours": 8.0, "sleep_score": 85,
        "body_battery_now": 82,
        "resting_hr": 48, "resting_hr_7d_avg": 49,
        "stress_avg": 25,
    })
    assert v.level in ("hard", "moderate")
    assert v.score >= 70


def test_verdict_no_data_is_not_confident():
    v = training_readiness_verdict({})
    assert v.score == 60
    assert v.level == "moderate"
    assert v.reasons


def test_trend_directions():
    assert trend([1, 2, 3, 4, 5]) == "rising"
    assert trend([5, 4, 3, 2, 1]) == "falling"
    assert trend([3, 3, 3, 3]) == "stable"
    assert trend([1, 2]) == "unknown"
    assert trend([None, None, 3]) == "unknown"


def test_sleep_debt():
    assert sleep_debt([7.5, 7.5, 7.5]) == 0.0
    assert sleep_debt([6.5, 6.5], target=7.5) == 2.0
    assert sleep_debt([9, 9], target=7.5) == 0.0  # extra sleep floored, not negative
    assert sleep_debt([6, None, 6], target=7.5) == 3.0


def test_weekly_load_ratio_and_flag():
    today = dt.date(2026, 9, 8)
    acts = [
        {"date": "2026-09-07", "training_load": 200},
        {"date": "2026-09-05", "training_load": 150},
        {"date": "2026-08-30", "training_load": 100},  # previous 7-day window
    ]
    r = weekly_load(acts, now_date=today)
    assert r["this_week"] == 350
    assert r["prev_week"] == 100
    assert r["ratio"] == 3.5
    assert r["flag"]


def test_weekly_load_falls_back_to_duration():
    today = dt.date(2026, 9, 8)
    acts = [{"date": "2026-09-06", "duration_min": 45}]
    r = weekly_load(acts, now_date=today)
    assert r["this_week"] == 45.0
    assert r["ratio"] is None
