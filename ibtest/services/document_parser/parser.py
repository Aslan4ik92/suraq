"""Извлечение текста из документов всех поддерживаемых форматов."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ibtest.services.document_parser import validation
from ibtest.services.document_parser.docx_reader import read_docx
from ibtest.services.document_parser.rtf import rtf_to_text
from ibtest.services.ocr.engine import OcrEngine, OcrUnavailable


class ParseError(Exception):
    def __init__(self, key: str, **kw):
        super().__init__(key)
        self.key, self.kw = key, kw


@dataclass
class ParsedDocument:
    text: str
    kind: str
    ocr_used: bool = False
    pages: int = 0
    warnings: list[str] = field(default_factory=list)


Progress = Callable[[int, int, str], None]


def normalize_text(text: str) -> str:
    """Нормализация без потери символов: NFC, единые пробелы и переводы строк."""
    t = unicodedata.normalize("NFC", text)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = t.replace("\u00ad", "")  # мягкий перенос
    t = re.sub(r"[\u00a0\u2007\u202f\u2002\u2003\u2009\t]", " ", t)
    t = t.replace("\u200b", "").replace("\ufeff", "")
    # Перенос слова на границе строк в PDF: «инфор-\nмации» -> «информации».
    t = re.sub(r"(?<=[а-яёәғқңөұүһіa-z])-\n(?=[а-яёәғқңөұүһіa-z])", "", t)
    t = re.sub(r"[ ]{2,}", " ", t)
    t = "\n".join(line.strip() for line in t.split("\n"))
    # Номера страниц отдельной строкой.
    t = re.sub(r"(?m)^\s*(?:-\s*)?\d{1,3}(?:\s*-)?\s*$\n?", "", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


_LEGACY_ONLY_1251 = set("ЉЊЌЋЏљњќћџЎўЈҐ")


def decode_text_bytes(data: bytes) -> tuple[str, list[str]]:
    """Декодирование TXT: UTF-8/UTF-16 по BOM, затем UTF-8, затем KZ-1048 или CP1251."""
    warnings: list[str] = []
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace"), warnings
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16"), warnings
    try:
        return data.decode("utf-8"), warnings
    except UnicodeDecodeError:
        pass
    as1251 = data.decode("cp1251", errors="replace")
    as1048 = data.decode("kz1048", errors="replace")
    # Казахская кодировка Windows (KZ-1048) отличается от CP1251 позициями
    # казахских букв. В CP1251 они выглядят как сербские/македонские буквы.
    if sum(as1251.count(c) for c in _LEGACY_ONLY_1251) > 3:
        warnings.append("txt_encoding_kz1048")
        return as1048, warnings
    warnings.append("txt_encoding_cp1251")
    return as1251, warnings


class DocumentParser:
    def __init__(self, ocr: OcrEngine, min_chars_per_page: int = 40, max_mb: int = 100):
        self.ocr = ocr
        self.min_chars = min_chars_per_page
        self.max_mb = max_mb

    def parse(self, path: Path, progress: Progress | None = None, force_ocr: bool = False) -> ParsedDocument:
        path = Path(path)
        try:
            kind = validation.detect_kind(path, self.max_mb)
        except validation.FileRejected as e:
            raise ParseError(e.key, **e.kw) from e
        warnings = []
        if kind == "docx_macro":
            warnings.append("docx_has_macros")
            kind = "docx"
        try:
            if kind == "pdf":
                res = self._pdf(path, progress, force_ocr)
            elif kind == "docx":
                res = ParsedDocument(read_docx(path), "docx")
            elif kind == "doc":
                res = self._doc(path)
            elif kind == "rtf":
                raw = path.read_bytes().decode("latin-1")
                res = ParsedDocument(rtf_to_text(raw), "rtf")
            elif kind == "txt":
                text, w = decode_text_bytes(path.read_bytes())
                res = ParsedDocument(text, "txt", warnings=w)
            elif kind == "image":
                res = ParsedDocument(self._ocr_image_file(path), "image", ocr_used=True, pages=1)
            else:
                raise ParseError("file_bad_ext", ext=path.suffix)
        except ParseError:
            raise
        except OcrUnavailable as e:
            raise ParseError("ocr_not_available", detail=str(e)) from e
        except Exception as e:  # повреждённый файл и т.п.
            raise ParseError("parse_failed", detail=f"{type(e).__name__}: {e}") from e
        res.warnings = warnings + res.warnings
        res.text = normalize_text(res.text)
        if len(res.text) < 50:
            raise ParseError("parse_empty")
        if "\ufffd" in res.text:
            res.warnings.append("text_has_replacement_chars")
        return res

    # -- PDF -----------------------------------------------------------------
    def _pdf(self, path: Path, progress: Progress | None, force_ocr: bool) -> ParsedDocument:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(path))
        n = len(pdf)
        texts, ocr_used, warnings = [], False, []
        try:
            for i in range(n):
                page = pdf[i]
                text = ""
                if not force_ocr:
                    tp = page.get_textpage()
                    text = tp.get_text_range() or ""
                    tp.close()
                if force_ocr or len(text.strip()) < self.min_chars:
                    if self.ocr.is_available():
                        if progress:
                            progress(i, n, "ocr")
                        img = page.render(scale=300 / 72).to_pil()
                        text = self.ocr.image_to_text(img)
                        ocr_used = True
                    elif text.strip() == "":
                        warnings.append("pdf_page_needs_ocr")
                page.close()
                texts.append(text)
                if progress:
                    progress(i + 1, n, "page")
        finally:
            pdf.close()
        if warnings and not "".join(texts).strip():
            raise ParseError("ocr_not_available", detail="scan")
        return ParsedDocument("\n\n".join(texts), "pdf", ocr_used=ocr_used, pages=n,
                              warnings=sorted(set(warnings)))

    # -- DOC -----------------------------------------------------------------
    def _doc(self, path: Path) -> ParsedDocument:
        tmpdir = Path(tempfile.mkdtemp(prefix="ibtest_doc_"))
        try:
            out = tmpdir / (path.stem + ".docx")
            if sys.platform == "win32" and self._convert_with_word(path, out):
                return ParsedDocument(read_docx(out), "doc")
            soffice = shutil.which("soffice") or shutil.which("libreoffice")
            if sys.platform == "win32" and not soffice:
                for c in (r"C:\Program Files\LibreOffice\program\soffice.exe",
                          r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"):
                    if Path(c).exists():
                        soffice = c
            if soffice:
                proc = subprocess.run([soffice, "--headless", "--norestore", "--convert-to", "docx",
                                       "--outdir", str(tmpdir), str(path)], capture_output=True, timeout=180)
                if proc.returncode == 0 and out.exists():
                    return ParsedDocument(read_docx(out), "doc")
            raise ParseError("doc_converter_missing")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @staticmethod
    def _convert_with_word(src: Path, dst: Path) -> bool:
        try:
            import win32com.client  # type: ignore
        except ImportError:
            return False
        word = None
        try:
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            d = word.Documents.Open(str(src.resolve()), ReadOnly=True, AddToRecentFiles=False)
            d.SaveAs2(str(dst.resolve()), FileFormat=16)
            d.Close(False)
            return dst.exists()
        except Exception:
            return False
        finally:
            if word is not None:
                try:
                    word.Quit()
                except Exception:
                    pass

    def _ocr_image_file(self, path: Path) -> str:
        return self.ocr.file_to_text(path)


# -- реквизиты приказа --------------------------------------------------------
_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
    "қаңтар": 1, "ақпан": 2, "наурыз": 3, "сәуір": 4, "мамыр": 5, "маусым": 6, "шілде": 7, "тамыз": 8,
    "қыркүйек": 9, "қазан": 10, "қараша": 11, "желтоқсан": 12,
}


def extract_requisites(text: str) -> dict:
    """Пытается найти номер и дату приказа в начале документа."""
    head = text[:3000]
    res: dict = {}
    m = re.search(r"№\s*([0-9A-Za-zА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі\-/\.]{1,20})", head)
    if m:
        res["doc_number"] = m.group(1).rstrip(".")
    m = re.search(r"\b(\d{1,2})[\.\-/](\d{1,2})[\.\-/](\d{4})\b", head)
    if m:
        d, mo, y = map(int, m.groups())
        if 1 <= d <= 31 and 1 <= mo <= 12:
            res["doc_date"] = f"{y:04d}-{mo:02d}-{d:02d}"
    else:
        m = re.search(r"«?(\d{1,2})»?\s+([а-яәғқңөұүһі]+)\s+(\d{4})", head, re.I)
        if m and m.group(2).lower() in _MONTHS:
            res["doc_date"] = f"{int(m.group(3)):04d}-{_MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
        else:
            m = re.search(r"(\d{4})\s+жылғы\s+(\d{1,2})\s+([а-яәғқңөұүһі]+)", head, re.I)
            if m and m.group(3).lower() in _MONTHS:
                res["doc_date"] = f"{int(m.group(1)):04d}-{_MONTHS[m.group(3).lower()]:02d}-{int(m.group(2)):02d}"
    return res
