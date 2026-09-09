"""Read/write the data export, transparently encrypting when a key is set up.

When ``config.get_data_passphrase()`` returns a passphrase, files are written as
``<name>.enc`` (AES-256-GCM) and any stale plaintext twin is removed. When it
returns None, files are written as plain ``<name>``. Readers accept either.
"""
from __future__ import annotations

import json
from pathlib import Path

import config
from crypto import decrypt, encrypt_text


def enabled() -> bool:
    return config.get_data_passphrase() is not None


def _pass() -> str | None:
    return config.get_data_passphrase()


def write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ph = _pass()
    if ph:
        enc = path.with_name(path.name + ".enc")
        enc.write_bytes(encrypt_text(text, ph))
        if path.exists():
            path.unlink()
        return enc
    path.write_text(text, encoding="utf-8")
    return path


def write_json(path: Path, obj) -> Path:
    return write_text(path, json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def read_text(path: Path) -> str:
    """``path`` is the logical name (e.g. ``latest.json``); tries plain then .enc."""
    if path.exists():
        return path.read_text(encoding="utf-8")
    enc = path.with_name(path.name + ".enc")
    if enc.exists():
        ph = _pass()
        if not ph:
            raise RuntimeError(f"{enc.name} is encrypted but no passphrase is configured")
        return decrypt(enc.read_bytes(), ph).decode("utf-8")
    raise FileNotFoundError(path)


def read_json(path: Path):
    return json.loads(read_text(path))


def iter_json(folder: Path):
    """Yield decoded objects from every ``*.json`` / ``*.json.enc`` in ``folder``."""
    seen: set[str] = set()
    for p in sorted(folder.glob("*.json*")):
        stem = p.name[:-4] if p.name.endswith(".enc") else p.name
        if not stem.endswith(".json") or stem in seen:
            continue
        seen.add(stem)
        try:
            yield read_json(folder / stem)
        except Exception as e:  # noqa: BLE001
            print(f"  ! skipping {p.name}: {e}")


def logical_names(folder: Path) -> list[str]:
    out = []
    for p in sorted(folder.glob("*")):
        if p.is_file():
            out.append(p.name[:-4] if p.name.endswith(".enc") else p.name)
    return sorted(set(out))


def encrypt_tree(root: Path) -> int:
    """Encrypt every plaintext .json/.csv/.md under ``root`` that isn't yet .enc.

    Used once when encryption is first switched on, to cover files an
    incremental sync won't rewrite. No-op when no passphrase is configured.
    """
    ph = _pass()
    if not ph:
        return 0
    n = 0
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix == ".enc":
            continue
        if p.suffix.lower() not in (".json", ".csv", ".md"):
            continue
        if p.with_name(p.name + ".enc").exists():
            p.unlink()
            continue
        p.with_name(p.name + ".enc").write_bytes(encrypt_text(p.read_text(encoding="utf-8"), ph))
        p.unlink()
        n += 1
    return n
