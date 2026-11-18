"""Проверка загружаемых файлов перед обработкой."""
from __future__ import annotations

import zipfile
from pathlib import Path

ALLOWED = {
    ".pdf": "pdf", ".docx": "docx", ".doc": "doc", ".txt": "txt", ".rtf": "rtf",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".tif": "image", ".tiff": "image", ".bmp": "image",
}

MAX_DOCX_UNCOMPRESSED = 300 * 1024 * 1024


class FileRejected(Exception):
    def __init__(self, key: str, **kw):
        super().__init__(key)
        self.key, self.kw = key, kw


def detect_kind(path: Path, max_mb: int = 100) -> str:
    """Возвращает тип файла после проверки расширения, размера и сигнатуры."""
    path = Path(path)
    if not path.is_file():
        raise FileRejected("file_not_found")
    ext = path.suffix.lower()
    if ext not in ALLOWED:
        raise FileRejected("file_bad_ext", ext=ext)
    size = path.stat().st_size
    if size == 0:
        raise FileRejected("file_empty")
    if size > max_mb * 1024 * 1024:
        raise FileRejected("file_too_big", mb=max_mb)
    kind = ALLOWED[ext]
    with open(path, "rb") as f:
        head = f.read(16)
    if kind == "pdf" and b"%PDF" not in head[:8] and not _pdf_header_later(path):
        raise FileRejected("file_bad_signature")
    if kind == "docx":
        if not head.startswith(b"PK"):
            raise FileRejected("file_bad_signature")
        try:
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                if "word/document.xml" not in names:
                    raise FileRejected("file_bad_signature")
                if sum(i.file_size for i in z.infolist()) > MAX_DOCX_UNCOMPRESSED:
                    raise FileRejected("file_zip_bomb")
                if any(n.lower().endswith("vbaproject.bin") for n in names):
                    # Макросы не исполняются, но предупреждаем через тип.
                    return "docx_macro"
        except zipfile.BadZipFile as exc:
            raise FileRejected("file_bad_signature") from exc
    if kind == "doc" and not head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        # Иногда .doc на самом деле RTF.
        if head.lstrip().startswith(b"{\\rtf"):
            return "rtf"
        raise FileRejected("file_bad_signature")
    if kind == "rtf" and not head.lstrip().startswith(b"{\\rtf"):
        raise FileRejected("file_bad_signature")
    if kind == "image":
        sigs = (b"\x89PNG", b"\xff\xd8\xff", b"II*\x00", b"MM\x00*", b"BM")
        if not head.startswith(sigs):
            raise FileRejected("file_bad_signature")
    if kind == "txt" and b"\x00" in head and not head.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise FileRejected("file_bad_signature")
    return kind


def _pdf_header_later(path: Path) -> bool:
    with open(path, "rb") as f:
        return b"%PDF" in f.read(1024)
