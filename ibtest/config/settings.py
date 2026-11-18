"""Настройки программы, хранящиеся в таблице application_settings."""
from __future__ import annotations

import json
from typing import Any

from ibtest.database.connection import Database
from ibtest.models.common import now_iso

DEFAULTS: dict[str, Any] = {
    "ui_language": "ru",
    "default_question_count": 30,
    "default_pass_score": 80,
    "default_time_limit_min": 40,
    # Локальная модель
    "ai_model_path": "",
    "ai_n_ctx": 8192,
    "ai_n_threads": 0,            # 0 = автоматически
    "ai_n_gpu_layers": 0,         # 0 = только CPU, -1 = все слои на GPU
    "ai_temperature": 0.3,
    "ai_top_p": 0.9,
    "ai_max_tokens": 3072,
    "ai_chunk_chars": 6000,
    "ai_questions_per_requirement": 2,
    "ai_verify_questions": True,  # второй проход самопроверки модели
    # OCR
    "ocr_tesseract_path": "",
    "ocr_languages": "rus+kaz+eng",
    "ocr_min_chars_per_page": 40,
    # Резервное копирование
    "backup_dir": "",
    "backup_auto_enabled": True,
    "backup_interval_hours": 24,
    "backup_keep": 10,
    "backup_include_documents": True,
    "backup_last_auto_at": "",
    "backup_password_protected": "",
    # Безопасность
    "admin_idle_lock_min": 15,
    "login_max_attempts": 5,
    "login_lock_minutes": 5,
    "max_upload_mb": 100,
    # Организация
    "organization_name": "",
}


class Settings:
    def __init__(self, db: Database):
        self.db = db

    def get(self, key: str, default: Any = None) -> Any:
        row = self.db.one("SELECT value FROM application_settings WHERE key = ?", (key,))
        if row is None or row["value"] is None:
            return DEFAULTS.get(key, default) if default is None else default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return row["value"]

    def set(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO application_settings(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), now_iso()))

    def set_many(self, values: dict[str, Any]) -> None:
        with self.db.transaction():
            for k, v in values.items():
                self.set(k, v)

    def all(self) -> dict[str, Any]:
        out = dict(DEFAULTS)
        for row in self.db.query("SELECT key, value FROM application_settings"):
            try:
                out[row["key"]] = json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                out[row["key"]] = row["value"]
        return out
