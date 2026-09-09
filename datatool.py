"""Read the (possibly encrypted) local Garmin data export.

    python datatool.py list                  # what's in the folder
    python datatool.py cat latest.json       # print one file, decrypted
    python datatool.py cat wellness.csv
    python datatool.py export ./plain        # decrypt everything into ./plain
    python datatool.py status                # is encryption on? where's the key?

Works whether or not encryption is enabled.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import config
import store

DEFAULT_OUT = Path(__file__).resolve().parent / "data"


def _resolve(out: Path, name: str) -> Path:
    """Accept 'latest.json', 'wellness/2026-09-08.json', with or without .enc."""
    name = name[:-4] if name.endswith(".enc") else name
    return out / name


def cmd_list(out: Path) -> int:
    if not out.exists():
        print(f"(no data folder at {out})")
        return 1
    for sub in (out, out / "wellness", out / "activities"):
        if not sub.exists():
            continue
        rel = sub.relative_to(out)
        prefix = "" if rel == Path(".") else f"{rel}/"
        for n in store.logical_names(sub):
            if (sub / n).is_dir():
                continue
            print(f"{prefix}{n}")
    return 0


def cmd_cat(out: Path, name: str) -> int:
    try:
        text = store.read_text(_resolve(out, name))
    except FileNotFoundError:
        print(f"not found: {name}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def cmd_export(out: Path, dest: str) -> int:
    d = Path(dest)
    d.mkdir(parents=True, exist_ok=True)
    n = 0
    for sub in (out, out / "wellness", out / "activities"):
        if not sub.exists():
            continue
        for name in store.logical_names(sub):
            src = sub / name
            if src.is_dir():
                continue
            try:
                text = store.read_text(src)
            except Exception as e:  # noqa: BLE001
                print(f"  ! {name}: {e}")
                continue
            target = d / sub.relative_to(out) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            n += 1
    print(f"Wrote {n} decrypted file(s) to {d.resolve()}")
    return 0


def cmd_status(out: Path) -> int:
    on = store.enabled()
    print(f"Encryption: {'ON (AES-256-GCM)' if on else 'OFF (plaintext)'}")
    if on:
        print(f"Key file:   {config.DATA_KEY_FILE}")
    print(f"Data dir:   {out}{' (exists)' if out.exists() else ' (missing)'}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read the local Garmin data export.")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    c = sub.add_parser("cat")
    c.add_argument("name")
    e = sub.add_parser("export")
    e.add_argument("dest")
    sub.add_parser("status")
    args = ap.parse_args(argv)

    out = Path(args.out)
    return {
        "list": lambda: cmd_list(out),
        "cat": lambda: cmd_cat(out, args.name),
        "export": lambda: cmd_export(out, args.dest),
        "status": lambda: cmd_status(out),
    }[args.cmd]()


if __name__ == "__main__":
    sys.exit(main())
