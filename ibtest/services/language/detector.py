"""Определение языка документа: русский или казахский.

Используются два признака: доля специфических казахских букв среди
кириллических и частотные служебные слова каждого языка.
"""
from __future__ import annotations

import re

KAZAKH_LETTERS = set("әғқңөұүһіӘҒҚҢӨҰҮҺІ")
KK_WORDS = {
    "және", "бойынша", "үшін", "мен", "болып", "тиіс", "немесе", "сондай", "қызметкер", "қызметкерлер",
    "ақпарат", "ақпараттық", "қауіпсіздік", "қауіпсіздігі", "талаптар", "талаптары", "жүйесі", "жүйелер",
    "бұйрық", "бұйрығы", "тармақ", "тармағы", "бөлім", "құпиясөз", "құпия", "рұқсат", "етіледі", "жатады",
    "болады", "қажет", "арқылы", "кезде", "кейін", "дейін", "туралы", "барлық", "өз", "оның", "осы", "бұл",
    "сәйкес", "жөніндегі", "қолдану", "пайдалану", "пайдаланушы", "тыйым", "салынады", "міндетті",
}
RU_WORDS = {
    "и", "в", "на", "не", "по", "для", "с", "что", "или", "при", "должен", "должны", "является",
    "информации", "безопасности", "сотрудник", "сотрудники", "приказ", "пункт", "запрещается", "допускается",
    "порядок", "требования", "системы", "работы", "обязан", "обязаны", "также", "который", "которые", "это",
}
_WORD = re.compile(r"[а-яёәғқңөұүһі]+", re.I)


def detect_language(text: str) -> str:
    """Возвращает 'kk', 'ru' или 'other'."""
    sample = text[:200_000]
    cyr = sum(1 for ch in sample if "Ѐ" <= ch <= "ӿ")
    latin = sum(1 for ch in sample if ch.isascii() and ch.isalpha())
    if cyr < 20 or cyr < latin * 0.3:
        return "other"
    kk_letters = sum(1 for ch in sample if ch in KAZAKH_LETTERS)
    words = [w.lower() for w in _WORD.findall(sample)]
    kk_hits = sum(1 for w in words if w in KK_WORDS)
    ru_hits = sum(1 for w in words if w in RU_WORDS)
    letter_ratio = kk_letters / cyr
    # В казахском тексте специфические буквы составляют обычно 5–12 % кириллицы;
    # в русском тексте с отдельными казахскими названиями — доли процента.
    if letter_ratio >= 0.03 and kk_hits >= ru_hits * 0.5:
        return "kk"
    if letter_ratio >= 0.015 and kk_hits > ru_hits:
        return "kk"
    return "ru"


def language_stats(text: str) -> dict:
    sample = text[:200_000]
    cyr = sum(1 for ch in sample if "Ѐ" <= ch <= "ӿ") or 1
    words = [w.lower() for w in _WORD.findall(sample)]
    return {
        "kk_letter_ratio": round(sum(1 for ch in sample if ch in KAZAKH_LETTERS) / cyr, 4),
        "kk_words": sum(1 for w in words if w in KK_WORDS),
        "ru_words": sum(1 for w in words if w in RU_WORDS),
    }
