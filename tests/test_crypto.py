import pytest

from crypto import decrypt, decrypt_text, encrypt, encrypt_text


def test_round_trip_bytes():
    blob = encrypt(b"resting_hr=39", "correct horse battery staple")
    assert blob != b"resting_hr=39"
    assert decrypt(blob, "correct horse battery staple") == b"resting_hr=39"


def test_round_trip_unicode_text():
    src = '{"מדד": "דופק", "value": 39}'
    blob = encrypt_text(src, "pw")
    assert decrypt_text(blob, "pw") == src


def test_wrong_passphrase_fails():
    blob = encrypt(b"secret", "right")
    with pytest.raises(Exception):
        decrypt(blob, "wrong")


def test_tampered_blob_fails():
    blob = bytearray(encrypt(b"secret metrics", "pw"))
    blob[-1] ^= 0x01  # flip a bit in the GCM tag
    with pytest.raises(Exception):
        decrypt(bytes(blob), "pw")


def test_not_our_format_fails():
    with pytest.raises(ValueError):
        decrypt(b"just some bytes", "pw")


def test_salt_and_nonce_are_random():
    a = encrypt(b"x", "pw")
    b = encrypt(b"x", "pw")
    assert a != b  # different salt+nonce each time
