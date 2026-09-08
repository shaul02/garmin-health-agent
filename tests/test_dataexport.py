from dataexport import build_activities_csv, build_wellness_csv, rolling


def test_rolling_partial_then_window():
    assert rolling([10], 3) == [None]
    assert rolling([10, 20], 3) == [None, 15.0]
    assert rolling([10, 20, 30, 40], 3) == [None, 15.0, 20.0, 30.0]
    # non-numeric values are skipped, not zeroed
    assert rolling([10, None, 20], 3) == [None, None, 15.0]


def test_build_wellness_csv_sorted_with_calc_columns():
    recs = [
        {"date": "2026-09-03", "hrv_last_night": 60, "resting_hr": 50, "sleep_hours": 7},
        {"date": "2026-09-01", "hrv_last_night": 50, "resting_hr": 48, "sleep_hours": 6},
        {"date": "2026-09-02", "hrv_last_night": 55, "resting_hr": 49, "sleep_hours": 8},
    ]
    csv_text = build_wellness_csv(recs)
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("date,sleep_hours")
    assert "hrv_7d_calc" in lines[0]
    # rows sorted ascending by date
    assert lines[1].startswith("2026-09-01")
    assert lines[3].startswith("2026-09-03")
    # 2nd row's rolling HRV avg = mean(50, 55) = 52.5
    assert "52.5" in lines[2]


def test_build_activities_csv_newest_first():
    rows = [
        {"date": "2026-09-01", "activity_id": 1, "type": "running", "distance_km": 5},
        {"date": "2026-09-05", "activity_id": 2, "type": "cycling", "distance_km": 20},
    ]
    csv_text = build_activities_csv(rows)
    lines = csv_text.strip().splitlines()
    assert lines[1].startswith("2026-09-05")
    assert lines[2].startswith("2026-09-01")


def test_build_wellness_csv_empty():
    assert build_wellness_csv([]).strip().startswith("date,")
