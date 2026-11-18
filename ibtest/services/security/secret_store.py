"""Хранение секретов (пароль шифрования резервных копий).

Windows: DPAPI (CryptProtectData) в области компьютера — секрет может
расшифровать только этот компьютер, файл БД на другом ПК бесполезен.
Другие ОС (разработка, тесты): ключ в файле данных с правами 0600.
"""
from __future__ import annotations

import base64
import ctypes
import os
import sys

from ibtest.config import paths

CRYPTPROTECT_LOCAL_MACHINE = 0x4
CRYPTPROTECT_UI_FORBIDDEN = 0x1
_ENTROPY = b"IBTest-secret-v1"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _dpapi(data: bytes, protect: bool) -> bytes:
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    inp, ent, out = _blob(data), _blob(_ENTROPY), _Blob()
    flags = CRYPTPROTECT_UI_FORBIDDEN | CRYPTPROTECT_LOCAL_MACHINE
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if protect:
        ok = fn(ctypes.byref(inp), "IBTest", ctypes.byref(ent), None, None, flags, ctypes.byref(out))
    else:
        ok = fn(ctypes.byref(inp), None, ctypes.byref(ent), None, None, flags, ctypes.byref(out))
    if not ok:
        raise OSError("DPAPI error")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def _fallback_key() -> bytes:
    from cryptography.fernet import Fernet
    kf = paths.data_dir() / ".secret.key"
    if not kf.exists():
        kf.write_bytes(Fernet.generate_key())
        try:
            os.chmod(kf, 0o600)
        except OSError:
            pass
    return kf.read_bytes()


def protect(secret: str) -> str:
    data = secret.encode("utf-8")
    if sys.platform == "win32":
        return "dpapi:" + base64.b64encode(_dpapi(data, True)).decode()
    from cryptography.fernet import Fernet
    return "fernet:" + Fernet(_fallback_key()).encrypt(data).decode()


def unprotect(stored: str) -> str:
    if not stored:
        return ""
    kind, _, payload = stored.partition(":")
    if kind == "dpapi":
        return _dpapi(base64.b64decode(payload), False).decode("utf-8")
    if kind == "fernet":
        from cryptography.fernet import Fernet
        return Fernet(_fallback_key()).decrypt(payload.encode()).decode("utf-8")
    raise ValueError("unknown secret format")
