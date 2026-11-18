"""Чтение DOCX с восстановлением автоматической нумерации Word.

python-docx возвращает текст абзацев без номеров, которые Word ставит
автоматически («1.», «1.1.», «а)»). Номера пунктов критичны для сравнения
редакций и ссылок вопросов на пункты, поэтому нумерация воспроизводится
по numbering.xml.
"""
from __future__ import annotations

from pathlib import Path

import docx
from docx.oxml.ns import qn

RU_LETTERS = "абвгдежзиклмнопрстуфхцчшщэюя"


def _fmt(n: int, fmt: str) -> str:
    if fmt in ("decimal", "decimalZero"):
        return f"{n:02d}" if fmt == "decimalZero" else str(n)
    if fmt == "lowerLetter":
        return chr(ord("a") + (n - 1) % 26)
    if fmt == "upperLetter":
        return chr(ord("A") + (n - 1) % 26)
    if fmt in ("russianLower",):
        return RU_LETTERS[(n - 1) % len(RU_LETTERS)]
    if fmt in ("russianUpper",):
        return RU_LETTERS[(n - 1) % len(RU_LETTERS)].upper()
    if fmt in ("lowerRoman", "upperRoman"):
        vals = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
                (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
        out, k = "", n
        for v, s in vals:
            while k >= v:
                out += s
                k -= v
        return out.upper() if fmt == "upperRoman" else out
    if fmt == "bullet" or fmt == "none":
        return ""
    return str(n)


class _Numbering:
    def __init__(self, document):
        self.abstract: dict[str, dict[int, dict]] = {}
        self.num_to_abs: dict[str, str] = {}
        self.overrides: dict[str, dict[int, int]] = {}
        self.counters: dict[str, dict[int, int]] = {}
        try:
            part = document.part.numbering_part
        except (KeyError, NotImplementedError, AttributeError):
            return
        root = part.element
        for absn in root.findall(qn("w:abstractNum")):
            aid = absn.get(qn("w:abstractNumId"))
            levels = {}
            for lvl in absn.findall(qn("w:lvl")):
                il = int(lvl.get(qn("w:ilvl")))
                start = lvl.find(qn("w:start"))
                fmt = lvl.find(qn("w:numFmt"))
                text = lvl.find(qn("w:lvlText"))
                levels[il] = {
                    "start": int(start.get(qn("w:val"))) if start is not None else 1,
                    "fmt": fmt.get(qn("w:val")) if fmt is not None else "decimal",
                    "text": text.get(qn("w:val")) if text is not None else "",
                }
            self.abstract[aid] = levels
        for num in root.findall(qn("w:num")):
            nid = num.get(qn("w:numId"))
            a = num.find(qn("w:abstractNumId"))
            if a is not None:
                self.num_to_abs[nid] = a.get(qn("w:val"))
            ov = {}
            for lo in num.findall(qn("w:lvlOverride")):
                so = lo.find(qn("w:startOverride"))
                if so is not None:
                    ov[int(lo.get(qn("w:ilvl")))] = int(so.get(qn("w:val")))
            self.overrides[nid] = ov

    def label(self, num_id: str, ilvl: int) -> str:
        aid = self.num_to_abs.get(num_id)
        if aid is None or aid not in self.abstract:
            return ""
        levels = self.abstract[aid]
        if ilvl not in levels:
            return ""
        # Счётчики ведутся по абстрактному списку (как в Word для одного списка).
        cnt = self.counters.setdefault(aid, {})
        start = self.overrides.get(num_id, {}).get(ilvl, levels[ilvl]["start"])
        cnt[ilvl] = cnt.get(ilvl, start - 1) + 1
        for deeper in [k for k in cnt if k > ilvl]:
            del cnt[deeper]
        text = levels[ilvl]["text"]
        if levels[ilvl]["fmt"] == "bullet":
            return "•"
        for lv in range(ilvl + 1):
            lvinfo = levels.get(lv, {"start": 1, "fmt": "decimal"})
            val = cnt.get(lv, lvinfo["start"])
            text = text.replace(f"%{lv + 1}", _fmt(val, lvinfo["fmt"]))
        return text.strip()


def _para_numpr(p, styles_numpr: dict) -> tuple[str, int] | None:
    ppr = p._p.pPr
    if ppr is not None and ppr.numPr is not None:
        numid = ppr.numPr.numId
        ilvl = ppr.numPr.ilvl
        if numid is not None and numid.val != 0:
            return str(numid.val), int(ilvl.val) if ilvl is not None else 0
        return None
    style_id = p._p.style
    if style_id and style_id in styles_numpr:
        return styles_numpr[style_id]
    return None


def read_docx(path: Path) -> str:
    document = docx.Document(str(path))
    numbering = _Numbering(document)
    styles_numpr: dict[str, tuple[str, int]] = {}
    try:
        for st in document.styles.element.findall(qn("w:style")):
            ppr = st.find(qn("w:pPr"))
            if ppr is None:
                continue
            numpr = ppr.find(qn("w:numPr"))
            if numpr is None:
                continue
            nid = numpr.find(qn("w:numId"))
            il = numpr.find(qn("w:ilvl"))
            if nid is not None:
                styles_numpr[st.get(qn("w:styleId"))] = (nid.get(qn("w:val")), int(il.get(qn("w:val"))) if il is not None else 0)
    except Exception:
        pass

    lines: list[str] = []
    body = document.element.body
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            p = Paragraph(child, document)
            text = p.text.strip()
            np = _para_numpr(p, styles_numpr)
            label = numbering.label(*np) if np else ""
            if text:
                lines.append(f"{label} {text}".strip() if label and label != "•" else (f"• {text}" if label == "•" else text))
            else:
                lines.append("")
        elif child.tag == qn("w:tbl"):
            t = Table(child, document)
            for row in t.rows:
                cells, seen = [], set()
                for c in row.cells:
                    if id(c._tc) in seen:
                        continue
                    seen.add(id(c._tc))
                    ct = " ".join(x.text.strip() for x in c.paragraphs if x.text.strip())
                    if ct:
                        cells.append(ct)
                if cells:
                    lines.append(" | ".join(cells))
            lines.append("")
    return "\n".join(lines)
