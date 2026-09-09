"""AES-256-GCM encryption for the local data export.

Blob layout (all binary, concatenated):

    magic "GHAE1"  (5 bytes)
    salt           (16 bytes)   -> PBKDF2-HMAC-SHA256, 200k iterations
    nonce          (12 bytes)
    ciphertext + GCM tag        (rest)

The passphrase never leaves the machine; the derived 256-bit key is held only
in memory. GCM authenticates the ciphertext, so tampering fails decryption
instead of returning garbage.
"""
from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.hashes import SHA256

_MAGIC = b"GHAE1"
_SALT_LEN = 16
_NONCE_LEN = 12
_ITERS = 200_000


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=SHA256(), length=32, salt=salt, iterations=_ITERS)
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt(data: bytes, passphrase: str) -> bytes:
    if not passphrase:
        raise ValueError("empty passphrase")
    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    key = _derive_key(passphrase, salt)
    ct = AESGCM(key).encrypt(nonce, data, None)
    return _MAGIC + salt + nonce + ct


def decrypt(blob: bytes, passphrase: str) -> bytes:
    head = _MAGIC + b"\x00" * (_SALT_LEN + _NONCE_LEN)
    if len(blob) < len(head) or not blob.startswith(_MAGIC):
        raise ValueError("not a GHAE1 encrypted blob")
    off = len(_MAGIC)
    salt = blob[off:off + _SALT_LEN]
    nonce = blob[off + _SALT_LEN:off + _SALT_LEN + _NONCE_LEN]
    ct = blob[off + _SALT_LEN + _NONCE_LEN:]
    key = _derive_key(passphrase, salt)
    return AESGCM(key).decrypt(nonce, ct, None)


def encrypt_text(text: str, passphrase: str) -> bytes:
    return encrypt(text.encode("utf-8"), passphrase)


def decrypt_text(blob: bytes, passphrase: str) -> str:
    return decrypt(blob, passphrase).decode("utf-8")
