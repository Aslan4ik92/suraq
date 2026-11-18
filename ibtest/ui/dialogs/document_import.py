"""Загрузка документа: выбор файла, извлечение текста, реквизиты."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLineEdit, QPlainTextEdit, QVBoxLayout)

from ibtest.localization.i18n import tr
from ibtest.services.document_parser.parser import extract_requisites
from ibtest.services.language.detector import detect_language
from ibtest.ui.widgets.common import button, confirm, error, label, warn
from ibtest.ui.workers import run_with_progress

FILE_FILTER = "Документы (*.pdf *.docx *.doc *.txt *.rtf *.png *.jpg *.jpeg *.tif *.tiff *.bmp)"


class DocumentImportDialog(QDialog):
    """mode='new' — новый документ, mode='revision' — новая редакция существующего."""

    def __init__(self, parent, ctx, mode: str = "new", document=None):
        super().__init__(parent)
        self.ctx, self.mode, self.document = ctx, mode, document
        self.path: Path | None = None
        self.parsed = None
        self.setWindowTitle(tr("imp_title_new") if mode == "new" else tr("imp_title_rev", title=document["title"]))
        self.resize(900, 720)
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.file_lbl = label(tr("imp_no_file"), "Muted")
        row.addWidget(button(tr("imp_choose"), self._choose, primary=True))
        self.ocr_cb = QCheckBox(tr("imp_force_ocr"))
        row.addWidget(self.ocr_cb)
        row.addWidget(self.file_lbl, 1)
        lay.addLayout(row)
        form = QFormLayout()
        self.title = QLineEdit(document["title"] if document else "")
        self.number = QLineEdit()
        self.date = QLineEdit()
        self.date.setPlaceholderText("ГГГГ-ММ-ДД")
        self.eff = QLineEdit()
        self.eff.setPlaceholderText("ГГГГ-ММ-ДД")
        self.lang = QComboBox()
        self.lang.addItem(tr("lang_ru"), "ru")
        self.lang.addItem(tr("lang_kk"), "kk")
        self.note = QLineEdit()
        if mode == "new":
            form.addRow(tr("imp_doc_title") + " *", self.title)
        form.addRow(tr("imp_number"), self.number)
        form.addRow(tr("imp_date"), self.date)
        form.addRow(tr("imp_effective"), self.eff)
        if mode == "new":
            form.addRow(tr("imp_language"), self.lang)
        form.addRow(tr("imp_note"), self.note)
        lay.addLayout(form)
        self.info = label("", "Muted", wrap=True)
        lay.addWidget(self.info)
        lay.addWidget(label(tr("imp_text_preview"), "H2"))
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        lay.addWidget(self.text, 1)
        bb = QDialogButtonBox()
        self.ok_btn = bb.addButton(tr("imp_save") if mode == "new" else tr("imp_save_rev"), QDialogButtonBox.AcceptRole)
        self.ok_btn.setProperty("primary", "true")
        self.ok_btn.setEnabled(False)
        bb.addButton(tr("cancel"), QDialogButtonBox.RejectRole)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.result_id = None
        self.revision = None

    def _choose(self):
        fn, _ = QFileDialog.getOpenFileName(self, tr("imp_choose"), "", FILE_FILTER)
        if not fn:
            return
        self.path = Path(fn)
        self.file_lbl.setText(self.path.name)
        force_ocr = self.ocr_cb.isChecked()
        path = self.path

        def job(progress, cancel):
            return self.ctx.documents.parse_file(path, progress=progress, force_ocr=force_ocr)

        res, err = run_with_progress(self, tr("imp_parsing"), job, cancellable=False)
        if err:
            error(self, err)
            return
        self.parsed = res
        self.text.setPlainText(res.text)
        lang = detect_language(res.text)
        req = extract_requisites(res.text)
        self.number.setText(req.get("doc_number", ""))
        self.date.setText(req.get("doc_date", ""))
        if self.mode == "new" and not self.title.text().strip():
            self.title.setText(self._guess_title(res.text) or self.path.stem)
        idx = self.lang.findData(lang if lang in ("ru", "kk") else "ru")
        self.lang.setCurrentIndex(idx)
        parts = [tr("imp_detected", lang=tr(f"lang_{lang}"), chars=len(res.text))]
        if res.ocr_used:
            parts.append(tr("imp_ocr_used"))
        for w in res.warnings:
            parts.append("⚠ " + tr(w))
        if lang == "other":
            parts.append("⚠ " + tr("imp_lang_other"))
        dup = self.ctx.documents.find_duplicate(self.path, res.text)
        if dup:
            parts.append("⚠ " + tr("imp_duplicate", title=dup.title, v=dup.version_no))
        self.info.setText("\n".join(parts))
        self.ok_btn.setEnabled(True)

    @staticmethod
    def _guess_title(text: str) -> str:
        lines = [l.strip() for l in text.split("\n")[:25] if l.strip()]
        for l in lines:
            low = l.lower()
            if low.startswith(("об утверждении", "о ", "об ")) or low.endswith(("туралы", "бекіту туралы")):
                return l[:200]
        return ""

    def _save(self):
        if not self.parsed or not self.path:
            return
        dup = self.ctx.documents.find_duplicate(self.path, self.parsed.text)
        if dup and self.mode == "new" and not confirm(self, tr("imp_duplicate_confirm", title=dup.title)):
            return
        try:
            if self.mode == "new":
                if not self.title.text().strip():
                    warn(self, tr("doc_title_empty"))
                    return
                self.result_id = self.ctx.documents.import_document(
                    self.path, self.parsed, self.title.text(), self.number.text().strip(), self.date.text().strip(),
                    self.eff.text().strip(), self.lang.currentData(), self.note.text().strip())
            else:
                self.revision = self.ctx.documents.add_revision(
                    self.document["id"], self.path, self.parsed, self.number.text().strip(), self.date.text().strip(),
                    self.eff.text().strip(), self.note.text().strip())
        except Exception as e:
            error(self, e)
            return
        self.accept()


class DocumentTextDialog(QDialog):
    def __init__(self, parent, title: str, text: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(860, 700)
        lay = QVBoxLayout(self)
        t = QPlainTextEdit(text)
        t.setReadOnly(True)
        lay.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Close).setText(tr("close"))
        lay.addWidget(bb)


class DocumentMetaDialog(QDialog):
    def __init__(self, parent, ctx, doc):
        super().__init__(parent)
        self.ctx, self.doc = ctx, doc
        self.setWindowTitle(tr("doc_card"))
        self.resize(560, 300)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.title = QLineEdit(doc["title"])
        self.number = QLineEdit(doc["doc_number"] or "")
        self.date = QLineEdit(doc["doc_date"] or "")
        self.eff = QLineEdit(doc["effective_date"] or "")
        self.lang = QComboBox()
        self.lang.addItem(tr("lang_ru"), "ru")
        self.lang.addItem(tr("lang_kk"), "kk")
        self.lang.setCurrentIndex(max(0, self.lang.findData(doc["language"])))
        self.mandatory = QCheckBox(tr("doc_mandatory"))
        self.mandatory.setChecked(bool(doc["is_mandatory"]))
        form.addRow(tr("imp_doc_title") + " *", self.title)
        form.addRow(tr("imp_number"), self.number)
        form.addRow(tr("imp_date"), self.date)
        form.addRow(tr("imp_effective"), self.eff)
        form.addRow(tr("imp_language"), self.lang)
        form.addRow("", self.mandatory)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText(tr("save"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("cancel"))
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _save(self):
        try:
            self.ctx.documents.update_meta(self.doc["id"], self.title.text(), self.number.text().strip(),
                                           self.date.text().strip(), self.eff.text().strip(), self.lang.currentData(),
                                           self.mandatory.isChecked())
        except Exception as e:
            error(self, e)
            return
        self.accept()
