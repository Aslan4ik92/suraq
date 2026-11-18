"""Шифрование резервных копий (AES-256-GCM, ключ из пароля через scrypt).

Используется, если администратор задал пароль шифрования резервных копий.
"""
from __future__ import annotations

import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"IBTENC1\x00"


def _key(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 15, r=8, p=1, dklen=32,
                          maxmem=128 * 1024 * 1024)


def encrypt_bytes(data: bytes, password: str) -> bytes:
    salt, nonce = os.urandom(16), os.urandom(12)
    ct = AESGCM(_key(password, salt)).encrypt(nonce, data, MAGIC)
    return MAGIC + salt + nonce + ct


def is_encrypted(blob: bytes) -> bool:
    return blob.startswith(MAGIC)


def decrypt_bytes(blob: bytes, password: str) -> bytes:
    if not is_encrypted(blob):
        raise ValueError("Файл не зашифрован")
    salt, nonce, ct = blob[8:24], blob[24:36], blob[36:]
    try:
        return AESGCM(_key(password, salt)).decrypt(nonce, ct, MAGIC)
    except Exception as exc:  # InvalidTag
        raise ValueError("Неверный пароль или файл повреждён") from exc


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
