"""Общие типы, перечисления и утилиты моделей."""
from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def new_uid(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex


def normalize_name(name: str) -> str:
    """Нормализация ФИО для поиска совпадений: регистр, ё/е, пробелы."""
    s = unicodedata.normalize("NFC", name or "").strip().lower().replace("ё", "е")
    return re.sub(r"\s+", " ", s)


def clean_person_name(name: str) -> str:
    s = re.sub(r"\s+", " ", unicodedata.normalize("NFC", name or "")).strip()
    return " ".join(w[:1].upper() + w[1:] if w else w for w in s.split(" "))


class DocStatus:
    ACTIVE = "active"
    REVISION_REVIEW = "revision_review"
    PENDING_UPDATE = "pending_update"
    ARCHIVED = "archived"
    REVOKED = "revoked"
    ALL = (ACTIVE, REVISION_REVIEW, PENDING_UPDATE, ARCHIVED, REVOKED)


class VersionStatus:
    DRAFT = "draft"
    REVIEW = "review"
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class QStatus:
    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    REJECTED = "rejected"
    OBSOLETE = "obsolete"
    ALL = (DRAFT, REVIEW, APPROVED, REJECTED, OBSOLETE)


class QType:
    SINGLE = "single"
    MULTIPLE = "multiple"
    TRUEFALSE = "truefalse"
    SITUATIONAL = "situational"
    ALL = (SINGLE, MULTIPLE, TRUEFALSE, SITUATIONAL)


DIFFICULTIES = ("easy", "medium", "hard")

TRUE_FALSE_LABELS = {
    "ru": ("Верно", "Неверно"),
    "kk": ("Дұрыс", "Бұрыс"),
}


@dataclass
class OptionData:
    text: str
    is_correct: bool


@dataclass
class QuestionData:
    """Вопрос до сохранения в БД (результат генерации или ручного ввода)."""
    qtype: str
    text: str
    options: list[OptionData]
    explanation: str = ""
    section_number: str = ""
    source_text: str = ""
    language: str = "ru"
    difficulty: str = "medium"
    requirement_text: str = ""
    category: str = ""
    extra: dict = field(default_factory=dict)

    def correct_indices(self) -> list[int]:
        return [i for i, o in enumerate(self.options) if o.is_correct]
