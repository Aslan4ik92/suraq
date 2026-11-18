"""Разбиение текста приказа на пункты."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

# «1.», «1.1.», «2.3.4», «5)» — номер пункта в начале строки.
_NUM = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){0,5})(\.|\))?\s+(?=\S)")
# Глава / раздел / статья (русский и казахский).
_HEAD = re.compile(
    r"^(?:(глава|раздел|статья|часть)\s+([0-9IVXLC]+)\.?|([0-9IVXLC]+)[\s\-–]*(тарау|бөлім|бап|бөлімі|тарауы))\b[\.\s]*(.*)$",
    re.I)
_SUBITEM = re.compile(r"^(?:[а-яәғқңөұүһіa-z]\)|[-–—•·▪]\s)", re.I)
_DATE_LIKE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{2,4}\b")


@dataclass
class Section:
    order_index: int
    number: str
    heading: str
    text: str
    top_group: str

    @property
    def norm_hash(self) -> str:
        return section_hash(self.text)


def normalize_for_compare(text: str) -> str:
    """Нормализация, при которой изменения форматирования не считаются
    изменением требования: регистр, пробелы, кавычки, тире, ё/е, пунктуация
    в конце строк, маркеры списков."""
    t = unicodedata.normalize("NFC", text).lower().replace("ё", "е")
    t = re.sub(r"[«»“”„\"'`’‘]", "", t)
    t = re.sub(r"[‐‑‒–—―]", "-", t)
    t = re.sub(r"(?m)^\s*[-•·▪]\s*", "", t)
    t = re.sub(r"[;:,\.]+(?=\s|$)", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def section_hash(text: str) -> str:
    return hashlib.sha256(normalize_for_compare(text).encode("utf-8")).hexdigest()


def text_hash(full_text: str) -> str:
    return hashlib.sha256(normalize_for_compare(full_text).encode("utf-8")).hexdigest()


def _is_number(line: str, prev_number: str | None, dotted_doc: bool):
    m = _NUM.match(line)
    if not m or _DATE_LIKE.match(line):
        return None
    num, term = m.group(1), m.group(2)
    if term == ")" and dotted_doc and "." not in num:
        # В документе с точечной нумерацией «1)» — подпункт, а не пункт.
        return None
    if term is None and "." not in num:
        # «2024 году …», «5 рабочих дней» — не номер пункта.
        return None
    return num


def split_sections(text: str) -> list[Section]:
    lines = [l.strip() for l in text.split("\n")]
    dotted_doc = sum(1 for l in lines if re.match(r"^\d{1,3}\.\d{1,3}\.?\s", l)) >= 2 or \
        sum(1 for l in lines if re.match(r"^\d{1,3}\.\s", l)) >= 3
    sections: list[Section] = []
    cur_num, cur_lines, cur_group, heading = "", [], "", ""
    preamble: list[str] = []

    def push():
        body = "\n".join(cur_lines).strip()
        if body:
            sections.append(Section(len(sections), cur_num, heading, body, cur_group or cur_num.split(".")[0]))

    started = False
    for line in lines:
        if not line:
            continue
        hm = _HEAD.match(line)
        if hm:
            if started:
                push()
                cur_lines, cur_num = [], ""
            grp = hm.group(2) or hm.group(3)
            cur_group = f"гл.{grp}"
            heading = line
            started = True
            continue
        num = _is_number(line, cur_num, dotted_doc)
        if num and not _SUBITEM.match(line):
            if started:
                push()
            elif preamble:
                sections.append(Section(0, "", "", "\n".join(preamble), "преамбула"))
                preamble = []
            started = True
            cur_num, cur_lines = num, [line]
            if not cur_group or (("." not in num) and not heading):
                cur_group = num.split(".")[0]
            continue
        if started:
            cur_lines.append(line)
        else:
            preamble.append(line)
    if started:
        push()

    if not any(s.number for s in sections):
        # Ненумерованный документ — пункты по абзацам.
        sections = []
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if len(paras) <= 2:
            paras = [l for l in lines if l]
        for i, p in enumerate(paras, start=1):
            sections.append(Section(i - 1, f"¶{i}", "", p, f"¶{(i - 1) // 10 + 1}"))
    elif preamble:
        sections.insert(0, Section(0, "", "", "\n".join(preamble), "преамбула"))
    for i, s in enumerate(sections):
        s.order_index = i
    return sections
