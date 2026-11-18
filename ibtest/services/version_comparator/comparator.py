"""Сравнение двух редакций приказа по пунктам."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any

from ibtest.services.document_parser.sections import normalize_for_compare

UNCHANGED, MODIFIED, ADDED, REMOVED, MANUAL = "unchanged", "modified", "added", "removed", "manual"

# Пороги сходства нормализованного текста.
SAME_NUMBER_MIN = 0.45     # тот же номер пункта: изменённый, если сходство выше
MOVED_MIN = 0.80           # другой номер: перенесённый/изменённый пункт
AMBIGUOUS_MIN = 0.55       # ниже MOVED_MIN, но выше этого — ручная проверка


@dataclass
class SectionRef:
    id: Any
    number: str
    text: str
    norm_hash: str


@dataclass
class Change:
    change_type: str
    old: SectionRef | None
    new: SectionRef | None
    similarity: float

    def word_diff(self) -> list[tuple[str, str]]:
        """Пословный дифф для отображения: [(тег, текст)], тег: equal/delete/insert."""
        a = (self.old.text if self.old else "").split()
        b = (self.new.text if self.new else "").split()
        out: list[tuple[str, str]] = []
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag == "equal":
                out.append(("equal", " ".join(a[i1:i2])))
            else:
                if i2 > i1:
                    out.append(("delete", " ".join(a[i1:i2])))
                if j2 > j1:
                    out.append(("insert", " ".join(b[j1:j2])))
        return out


_TOKEN = re.compile(r"\w+", re.U)


def similarity(a: str, b: str) -> float:
    na, nb = normalize_for_compare(a), normalize_for_compare(b)
    if na == nb:
        return 1.0
    ta, tb = _TOKEN.findall(na), _TOKEN.findall(nb)
    if not ta or not tb:
        return 0.0
    sa, sb = set(ta), set(tb)
    jacc = len(sa & sb) / len(sa | sb)
    if jacc < 0.2:
        return jacc
    seq = difflib.SequenceMatcher(None, ta, tb, autojunk=False).ratio()
    return round(max(seq, jacc * 0.9), 4)


def _strip_number(text: str) -> str:
    return re.sub(r"^\s*\d{1,3}(?:\.\d{1,3})*[\.\)]?\s+", "", text, count=1)


def compare(old: list[SectionRef], new: list[SectionRef]) -> list[Change]:
    changes: list[Change] = []
    old_left = {o.id: o for o in old}
    new_left = {n.id: n for n in new}

    # 1. Совпадение нормализованного текста (в т.ч. без учёта номера пункта —
    #    перенумерация не меняет требование).
    by_hash: dict[str, list[SectionRef]] = {}
    for o in old:
        by_hash.setdefault(normalize_for_compare(_strip_number(o.text)), []).append(o)
    for n in new:
        key = normalize_for_compare(_strip_number(n.text))
        cands = [o for o in by_hash.get(key, []) if o.id in old_left]
        if cands:
            o = next((c for c in cands if c.number == n.number), cands[0])
            changes.append(Change(UNCHANGED, o, n, 1.0))
            del old_left[o.id]
            del new_left[n.id]

    # 2. Тот же номер пункта.
    old_by_num = {}
    for o in old_left.values():
        if o.number:
            old_by_num.setdefault(o.number, o)
    for n in list(new_left.values()):
        o = old_by_num.get(n.number) if n.number else None
        if o is None or o.id not in old_left:
            continue
        sim = similarity(_strip_number(o.text), _strip_number(n.text))
        if sim >= SAME_NUMBER_MIN:
            changes.append(Change(MODIFIED, o, n, sim))
            del old_left[o.id]
            del new_left[n.id]

    # 3. Сопоставление по содержанию (перенесённые пункты).
    pairs = []
    for n in new_left.values():
        for o in old_left.values():
            sim = similarity(_strip_number(o.text), _strip_number(n.text))
            if sim >= AMBIGUOUS_MIN:
                pairs.append((sim, o.id, n.id))
    pairs.sort(reverse=True)
    for sim, oid, nid in pairs:
        if oid in old_left and nid in new_left:
            ctype = MODIFIED if sim >= MOVED_MIN else MANUAL
            changes.append(Change(ctype, old_left.pop(oid), new_left.pop(nid), sim))

    changes += [Change(REMOVED, o, None, 0.0) for o in old_left.values()]
    changes += [Change(ADDED, None, n, 0.0) for n in new_left.values()]

    order_new = {n.id: i for i, n in enumerate(new)}
    order_old = {o.id: i for i, o in enumerate(old)}
    changes.sort(key=lambda c: (order_new.get(c.new.id, 10 ** 6) if c.new else order_old.get(c.old.id, 0) + 0.5))
    return changes


def summarize(changes: list[Change]) -> dict[str, int]:
    out = {UNCHANGED: 0, MODIFIED: 0, ADDED: 0, REMOVED: 0, MANUAL: 0}
    for c in changes:
        out[c.change_type] += 1
    return out
