"""Хеширование паролей: scrypt (RFC 7914) из стандартной библиотеки.

Формат: scrypt$N$r$p$salt_b64$hash_b64. Параметры можно усиливать — старые
хеши продолжают проверяться, а при входе пересчитываются (needs_rehash).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

N, R, P, DKLEN = 2 ** 15, 8, 1, 64
MAXMEM = 128 * 1024 * 1024
MIN_LENGTH = 8


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=N, r=R, p=P, dklen=DKLEN, maxmem=MAXMEM)
    return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(hash_b64)
        dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p),
                            dklen=len(expected), maxmem=MAXMEM)
        return hmac.compare_digest(dk, expected)
    except (ValueError, TypeError):
        return False


def needs_rehash(stored: str) -> bool:
    try:
        _, n, r, p, *_ = stored.split("$")
        return (int(n), int(r), int(p)) != (N, R, P)
    except ValueError:
        return True


def password_problems(password: str) -> list[str]:
    """Проверка сложности пароля администратора. Возвращает ключи локализации."""
    probs = []
    if len(password) < MIN_LENGTH:
        probs.append("pwd_too_short")
    if not any(c.isdigit() for c in password):
        probs.append("pwd_need_digit")
    if not any(c.isalpha() for c in password):
        probs.append("pwd_need_letter")
    if password.lower() == password or password.upper() == password:
        probs.append("pwd_need_case")
    return probs
