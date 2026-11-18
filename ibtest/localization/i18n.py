"""Локализация интерфейса: русский и казахский."""
from __future__ import annotations

from ibtest.localization import kk, ru

_LANGS = {"ru": ru.STRINGS, "kk": kk.STRINGS}
_current = "ru"


def set_language(lang: str) -> None:
    global _current
    _current = lang if lang in _LANGS else "ru"


def language() -> str:
    return _current


def tr(key: str, **kw) -> str:
    s = _LANGS[_current].get(key) or ru.STRINGS.get(key) or key
    if kw:
        try:
            return s.format(**kw)
        except (KeyError, IndexError, ValueError):
            return s
    return s


def tr_error(exc: Exception) -> str:
    """Текст ошибки сервиса: исключения несут ключ локализации и параметры."""
    key = getattr(exc, "key", None)
    if key:
        kw = dict(getattr(exc, "kw", {}) or {})
        text = tr(key, **kw)
        if "detail" in kw and "{detail}" not in (_LANGS[_current].get(key) or ""):
            text += f"\n{kw['detail']}"
        return text
    msg = str(exc)
    return tr(msg) if msg in _LANGS[_current] else msg
