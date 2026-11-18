"""Самопроверка установленной программы без графического интерфейса.

IBTest.exe --selftest отчёт.txt — проверяет компоненты на этом компьютере
и записывает отчёт. Код возврата 0 — все обязательные проверки пройдены.
Используется при сборке и для диагностики у пользователя (интернет не нужен).
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path


def run(report_path: str | None) -> int:
    lines: list[str] = []
    ok_all = True

    def check(name: str, fn, required: bool = True):
        nonlocal ok_all
        try:
            detail = fn() or ""
            lines.append(f"[OK]   {name} {detail}")
        except Exception as e:
            lines.append(f"[{'FAIL' if required else 'WARN'}] {name}: {type(e).__name__}: {e}")
            if required:
                ok_all = False

    from ibtest import __version__
    lines.append(f"ИБ ТЕСТ {__version__} — самопроверка")

    tmp = tempfile.mkdtemp(prefix="ibtest_selftest_")
    os.environ["IBTEST_DATA_DIR"] = tmp

    def gui():
        import PySide6
        from PySide6 import QtCore, QtPrintSupport, QtWidgets  # noqa: F401
        return PySide6.__version__

    def db():
        from ibtest.app_context import AppContext
        ctx = AppContext()
        ok, msg = ctx.db.integrity_check()
        ctx.db.close()
        if not ok:
            raise RuntimeError(msg)
        return "schema ok"

    def kazakh_roundtrip():
        from ibtest.app_context import AppContext
        ctx = AppContext()
        name = "Әбілқасымов Ғалым Құрманұлы"
        eid = ctx.employees.find_or_create(name, "Қаржы бөлімі")
        got = ctx.employees.get(eid)["full_name"]
        ctx.db.close()
        if got != name:
            raise RuntimeError(f"{got!r} != {name!r}")

    def docx_parse():
        import docx
        from ibtest.services.document_parser.parser import DocumentParser
        from ibtest.services.ocr.engine import OcrEngine
        d = docx.Document()
        d.add_paragraph("1.1. Құпиясөз кемінде 12 таңбадан тұруы тиіс. Пароль не менее 12 символов.")
        d.add_paragraph("1.2. Өз құпиясөзіңізді басқа тұлғаларға беруге тыйым салынады.")
        p = Path(tmp) / "t.docx"
        d.save(p)
        res = DocumentParser(OcrEngine()).parse(p)
        if "Құпиясөз" not in res.text:
            raise RuntimeError("kazakh letters lost")

    def pdf():
        import pypdfium2
        return getattr(pypdfium2, "PDFIUM_INFO", "")

    def reports():
        from ibtest.services.report_generator.reports import Report, export_excel, export_pdf
        r = Report("Тест есебі — Әә Ғғ Ққ Ңң Өө Ұұ Үү Һһ Іі", summary={"tests": 0})
        export_excel(r, Path(tmp) / "r.xlsx")
        export_pdf(r, Path(tmp) / "r.pdf")

    def llama():
        import llama_cpp
        gpu = getattr(llama_cpp, "llama_supports_gpu_offload", lambda: False)()
        return f"{llama_cpp.__version__} gpu={bool(gpu)}"

    def ocr():
        from ibtest.services.ocr.engine import OcrEngine
        o = OcrEngine(languages="rus+kaz+eng")
        langs = o.available_languages()
        missing = [l for l in ("rus", "kaz") if l not in langs]
        if missing:
            raise RuntimeError("нет языков: " + ",".join(missing))
        return o.executable()

    def system():
        from ibtest.services.ai_engine.system_check import system_info
        si = system_info()
        return f"{si.os}, CPU {si.cpu_count}, RAM {si.ram_total_gb} GB"

    check("Qt (PySide6)", gui)
    check("База данных SQLite", db)
    check("Казахские символы в БД", kazakh_roundtrip)
    check("Чтение DOCX", docx_parse)
    check("PDF (pdfium)", pdf)
    check("Отчёты Excel/PDF", reports)
    check("llama.cpp", llama)
    check("Tesseract OCR", ocr, required=False)
    check("Система", system, required=False)
    lines.append("ИТОГ: " + ("OK" if ok_all else "ЕСТЬ ОШИБКИ"))
    text = "\n".join(lines)
    if report_path:
        Path(report_path).write_text(text, encoding="utf-8")
    else:
        try:
            print(text)
        except Exception:
            pass
    return 0 if ok_all else 1


if __name__ == "__main__":
    try:
        sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else None))
    except Exception:
        traceback.print_exc()
        sys.exit(2)
