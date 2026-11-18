"""Сборка всех сервисов приложения в одном контексте."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ibtest.config import paths
from ibtest.config.settings import Settings
from ibtest.database.connection import Database
from ibtest.services.ai_engine.llm import GenerationParams, get_engine
from ibtest.services.analytics.results import ResultsService
from ibtest.services.backup.backup import BackupService
from ibtest.services.document_parser.parser import DocumentParser
from ibtest.services.documents import DocumentService
from ibtest.services.employees import EmployeeService
from ibtest.services.ocr.engine import OcrEngine
from ibtest.services.question_generator.generator import QuestionGenerator
from ibtest.services.questions import QuestionService
from ibtest.services.security.auth import AuditLog, AuthService
from ibtest.services.test_engine.engine import ProfileService, TestEngine


def setup_logging() -> None:
    root = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return
    h = RotatingFileHandler(paths.logs_dir() / "ibtest.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(h)
    root.setLevel(logging.INFO)


class AppContext:
    def __init__(self, db_path: Path | None = None):
        self.db = Database(db_path)
        self.settings = Settings(self.db)
        self.audit = AuditLog(self.db)
        self.auth = AuthService(self.db, self.settings, self.audit)
        self.employees = EmployeeService(self.db, self.audit)
        self.questions = QuestionService(self.db, self.audit)
        self.ocr = OcrEngine(self.settings.get("ocr_tesseract_path"), self.settings.get("ocr_languages"))
        self.parser = DocumentParser(self.ocr, int(self.settings.get("ocr_min_chars_per_page")),
                                     int(self.settings.get("max_upload_mb")))
        self.documents = DocumentService(self.db, self.audit, self.parser, self.questions)
        self.profiles = ProfileService(self.db, self.audit)
        self.tests = TestEngine(self.db, self.audit)
        self.results = ResultsService(self.db)
        self.backup = BackupService(self.db, self.settings, self.audit)

    def autodetect_model(self) -> str | None:
        """Если модель не указана, а пакет модели установлен в папку моделей, — подключить её."""
        if self.settings.get("ai_model_path"):
            return None
        found = sorted(paths.models_dir().glob("*.gguf"), key=lambda p: p.stat().st_size, reverse=True)
        if not found:
            return None
        self.settings.set("ai_model_path", str(found[0]))
        self.audit.log("settings_ai", "application_settings", None, {"model": found[0].name, "auto": True})
        return str(found[0])

    def reload_settings(self) -> None:
        self.ocr.tesseract_path = self.settings.get("ocr_tesseract_path")
        self.ocr.languages = self.settings.get("ocr_languages")
        self.ocr._exe = None
        self.ocr._langs = None
        self.parser.min_chars = int(self.settings.get("ocr_min_chars_per_page"))
        self.parser.max_mb = int(self.settings.get("max_upload_mb"))

    def generation_params(self) -> GenerationParams:
        s = self.settings
        return GenerationParams(temperature=float(s.get("ai_temperature")), top_p=float(s.get("ai_top_p")),
                                max_tokens=int(s.get("ai_max_tokens")))

    def make_generator(self, backend=None) -> QuestionGenerator:
        """Генератор вопросов на локальной модели. Без модели — исключение
        ModelNotConfigured: подмены AI-генерации шаблонами нет."""
        s = self.settings
        if backend is None:
            backend = get_engine(s.get("ai_model_path"), int(s.get("ai_n_ctx")), int(s.get("ai_n_threads")),
                                 int(s.get("ai_n_gpu_layers")))
        return QuestionGenerator(self.db, self.questions, self.audit, backend, self.generation_params(),
                                 chunk_chars=int(s.get("ai_chunk_chars")),
                                 per_requirement=int(s.get("ai_questions_per_requirement")),
                                 verify=bool(s.get("ai_verify_questions")))
