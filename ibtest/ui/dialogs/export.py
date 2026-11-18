"""Экспорт отчётов в Excel/PDF и печать."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import QFileDialog

from ibtest.config import paths
from ibtest.localization.i18n import tr
from ibtest.services.report_generator.reports import Report, export_excel, export_pdf, to_html
from ibtest.ui.widgets.common import confirm, error


def export_report(parent, ctx, report: Report, kind: str, base_name: str = "report") -> Path | None:
    report.organization = ctx.settings.get("organization_name") or ""
    ext = "xlsx" if kind == "excel" else "pdf"
    default = paths.exports_dir() / f"{base_name}_{datetime.now():%Y%m%d_%H%M}.{ext}"
    flt = "Excel (*.xlsx)" if kind == "excel" else "PDF (*.pdf)"
    fn, _ = QFileDialog.getSaveFileName(parent, tr("export_title"), str(default), flt)
    if not fn:
        return None
    try:
        path = export_excel(report, Path(fn)) if kind == "excel" else export_pdf(report, Path(fn))
    except PermissionError:
        error(parent, tr("export_locked"))
        return None
    except Exception as e:
        error(parent, e)
        return None
    if not path.exists() or path.stat().st_size == 0:
        error(parent, tr("export_failed"))
        return None
    ctx.audit.log("report_export", "reports", None, {"file": path.name, "kind": kind, "rows": len(report.results)})
    if confirm(parent, tr("export_done_open", path=str(path))):
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
    return path


def print_report(parent, ctx, report: Report) -> None:
    report.organization = ctx.settings.get("organization_name") or ""
    printer = QPrinter(QPrinter.HighResolution)
    dlg = QPrintDialog(printer, parent)
    if not dlg.exec():
        return
    doc = QTextDocument()
    doc.setHtml(to_html(report))
    doc.print_(printer)
    ctx.audit.log("report_print", "reports", None, {"rows": len(report.results)})
