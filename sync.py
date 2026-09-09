"""Sync my own Garmin data into a local folder.

Read-only: every Garmin call here is a GET (workouts + recovery metrics).
Nothing is ever written back to the Garmin account. The only things written
outside ``--out`` are the OAuth token cache and (with --encrypt) the data key,
both under ``~/.garmin-health-agent/``.

Usage:
    python sync.py                 # last 30 days of wellness + 30 recent workouts
    python sync.py --days 90       # backfill more history
    python sync.py --full          # re-fetch days already on disk
    python sync.py --encrypt       # turn on AES-256 encryption of the data folder

Output layout (default ``./data``; files become ``<name>.enc`` when encrypted):
    data/latest.json            <- start here: today + last 7 days + recent workouts
    data/wellness.csv           <- one row per day
    data/activities.csv         <- one row per workout
    data/wellness/<date>.json   <- full day detail
    data/activities/<id>.json   <- full workout detail
    data/README.md
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

import config
import store
from dataexport import build_activities_csv, build_wellness_csv
from garmin_client import GarminData, GarminConnectTooManyRequestsError

# Anchor the default output next to this script, so a scheduled task that runs
# from any working directory still writes to the project's own data/ folder.
DEFAULT_OUT = Path(__file__).resolve().parent / "data"


def _have(path: Path) -> bool:
    return path.exists() or path.with_name(path.name + ".enc").exists()


def sync_wellness(g: GarminData, out: Path, days: int, full: bool) -> int:
    folder = out / "wellness"
    folder.mkdir(parents=True, exist_ok=True)
    today = dt.date.today()
    fetched = 0
    print(f"Recovery data - checking the last {days} days...")
    for i in range(days):
        d = today - dt.timedelta(days=i)
        ds = d.isoformat()
        fp = folder / f"{ds}.json"
        if _have(fp) and not full and d != today:
            continue
        try:
            rec = g.daily_record(ds)
        except GarminConnectTooManyRequestsError:
            print("  ! Garmin is rate-limiting. Saving what we have - re-run in ~15 min.")
            break
        store.write_json(fp, rec)
        fetched += 1
        got = [k for k in ("sleep_hours", "hrv_last_night", "resting_hr",
                           "body_battery_high", "training_readiness") if rec.get(k) is not None]
        print(f"  {ds}: {', '.join(got) if got else 'no data yet'}")
        time.sleep(0.3)

    records = list(store.iter_json(folder))
    store.write_text(out / "wellness.csv", build_wellness_csv(records))
    print(f"  -> {len(records)} days in wellness.csv ({fetched} newly fetched)")
    return fetched


def sync_activities(g: GarminData, out: Path, limit: int) -> int:
    folder = out / "activities"
    folder.mkdir(parents=True, exist_ok=True)
    print(f"Workouts - fetching the {limit} most recent...")
    acts = g.recent_activities(limit=limit)
    new = 0
    for a in acts:
        aid = a.get("activity_id")
        if not aid:
            continue
        fp = folder / f"{aid}.json"
        if _have(fp):
            continue
        detail = None
        try:
            detail = g.activity_detail(aid)
        except GarminConnectTooManyRequestsError:
            print("  ! rate-limited; stopping workout detail fetch.")
            break
        store.write_json(fp, {"summary": a, "details": detail})
        new += 1
        print(f"  + {a.get('date')} {a.get('type')} {a.get('distance_km') or ''}")
        time.sleep(0.3)

    summaries = [rec.get("summary", rec) for rec in store.iter_json(folder)]
    store.write_text(out / "activities.csv", build_activities_csv(summaries))
    print(f"  -> {len(summaries)} workouts in activities.csv ({new} new)")
    return new


def write_latest(g: GarminData, out: Path) -> None:
    today = dt.date.today().isoformat()
    week = sorted(store.iter_json(out / "wellness"), key=lambda r: r.get("date") or "")[-7:]
    latest = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "today": g.wellness_snapshot(today),
        "week": week,
        "recent_activities": g.recent_activities(limit=10),
        "note": "Read-only export of my own Garmin Connect data.",
    }
    store.write_json(out / "latest.json", latest)


def write_readme(out: Path) -> None:
    enc = " (encrypted as *.enc — use `python datatool.py cat <name>`)" if store.enabled() else ""
    store.write_text(
        out / "README.md",
        "# Garmin data export\n\n"
        f"Read-only mirror of my own Garmin Connect data, refreshed by `sync.py`{enc}.\n"
        "Nothing here is written back to Garmin.\n\n"
        "- **latest.json** - today's recovery snapshot + last 7 days + recent workouts. Start here.\n"
        "- **wellness.csv** - one row per day: sleep, HRV, resting HR, Body Battery, stress, "
        "SpO2, training readiness (`*_7d_calc` columns are computed from this file).\n"
        "- **activities.csv** - one row per workout.\n"
        "- **wellness/<date>.json**, **activities/<id>.json** - full detail.\n\n"
        f"Last sync: {dt.datetime.now().isoformat(timespec='seconds')}\n",
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sync my Garmin data into a local folder (read-only).")
    ap.add_argument("--days", type=int, default=30, help="how many days of recovery data (default 30)")
    ap.add_argument("--activities", type=int, default=30, help="how many recent workouts (default 30)")
    ap.add_argument("--full", action="store_true", help="re-fetch days already saved")
    ap.add_argument("--encrypt", action="store_true",
                    help="enable AES-256 encryption of the data folder (provisions a key on first use)")
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="output folder (default: the project's data/ folder)")
    args = ap.parse_args(argv)

    out = Path(args.out)

    if args.encrypt:
        config.ensure_data_passphrase()
        print(f"Encryption ON. Key file: {config.DATA_KEY_FILE}")
        print("Keep that file safe and backed up — without it the data cannot be read.\n")
    if store.enabled():
        moved = store.encrypt_tree(out) if out.exists() else 0
        if moved:
            print(f"Encrypted {moved} existing file(s).\n")

    print("Connecting to Garmin Connect...")
    g = GarminData()
    try:
        g.connect_interactive()
    except Exception as e:  # noqa: BLE001
        print(f"\nCould not connect: {e}")
        print("Check the e-mail/password in .streamlit/secrets.toml and try again.")
        return 1
    print("Connected.\n")

    sync_wellness(g, out, args.days, args.full)
    print()
    sync_activities(g, out, args.activities)
    print()
    write_latest(g, out)
    write_readme(out)

    lock = " (encrypted)" if store.enabled() else ""
    print(f"\nDone. Data is in: {out.resolve()}{lock}")
    print("Point me at that folder any time and I'll read the latest numbers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
