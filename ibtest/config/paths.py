"""Расположение данных приложения.

Данные никогда не хранятся в папке установки. По умолчанию используется
общая папка ProgramData (компьютер, на котором тест проходят разные
сотрудники под разными учётными записями Windows). Установщик выдаёт группе
«Пользователи» права на изменение этой папки. Если папка недоступна для
записи (портативный запуск без установщика), используется LocalAppData.

Переменная окружения IBTEST_DATA_DIR переопределяет путь (тесты, отладка).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from ibtest import __app_id__

_cached: Path | None = None


def _is_writable(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def data_dir() -> Path:
    global _cached
    if _cached is not None:
        return _cached
    override = os.environ.get("IBTEST_DATA_DIR")
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    elif sys.platform == "win32":
        if os.environ.get("PROGRAMDATA"):
            candidates.append(Path(os.environ["PROGRAMDATA"]) / __app_id__)
        if os.environ.get("LOCALAPPDATA"):
            candidates.append(Path(os.environ["LOCALAPPDATA"]) / __app_id__)
    else:
        candidates.append(Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / __app_id__)
    for c in candidates:
        if _is_writable(c):
            _cached = c
            break
    else:
        raise RuntimeError("Нет доступной для записи папки данных: " + ", ".join(map(str, candidates)))
    for sub in ("documents", "backups", "models", "logs", "exports", "tmp"):
        (_cached / sub).mkdir(parents=True, exist_ok=True)
    return _cached


def reset_cache() -> None:
    global _cached
    _cached = None


def db_path() -> Path:
    return data_dir() / "ib_test.db"


def documents_dir() -> Path:
    return data_dir() / "documents"


def backups_dir() -> Path:
    return data_dir() / "backups"


def models_dir() -> Path:
    return data_dir() / "models"


def logs_dir() -> Path:
    return data_dir() / "logs"


def exports_dir() -> Path:
    return data_dir() / "exports"


def tmp_dir() -> Path:
    return data_dir() / "tmp"


def app_root() -> Path:
    """Папка с ресурсами программы (учитывает сборку PyInstaller)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "ibtest"
    return Path(__file__).resolve().parent.parent


def install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return app_root().parent


def assets_dir() -> Path:
    return app_root() / "assets"


def bundled_tesseract() -> Path | None:
    """Tesseract, поставляемый установщиком: {app}\\tesseract\\tesseract.exe."""
    exe = install_dir() / "tesseract" / ("tesseract.exe" if sys.platform == "win32" else "tesseract")
    return exe if exe.exists() else None
