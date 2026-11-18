"""Создание и редактирование вопроса."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout, QLineEdit,
                               QPlainTextEdit, QVBoxLayout)

from ibtest.localization.i18n import tr
from ibtest.models.common import DIFFICULTIES, OptionData, QType, QuestionData, TRUE_FALSE_LABELS
from ibtest.services.questions import validate_question
from ibtest.ui.widgets.common import button, error, label, warn

MAX_OPTIONS = 6


class QuestionEditor(QDialog):
    def __init__(self, parent, ctx, qid: int | None = None, document_id: int | None = None):
        super().__init__(parent)
        self.ctx, self.qid = ctx, qid
        self.setWindowTitle(tr("qe_edit") if qid else tr("qe_new"))
        self.resize(820, 680)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.doc = QComboBox()
        for d in ctx.documents.list(include_archived=False):
            self.doc.addItem(d["title"], d["id"])
        self.section = QComboBox()
        self.section.setEditable(False)
        self.doc.currentIndexChanged.connect(self._load_sections)
        self.qtype = QComboBox()
        for t in QType.ALL:
            self.qtype.addItem(tr(f"qt_{t}"), t)
        self.qtype.currentIndexChanged.connect(self._type_changed)
        self.diff = QComboBox()
        for d in DIFFICULTIES:
            self.diff.addItem(tr(f"diff_{d}"), d)
        self.lang = QComboBox()
        self.lang.addItem(tr("lang_ru"), "ru")
        self.lang.addItem(tr("lang_kk"), "kk")
        self.lang.currentIndexChanged.connect(self._type_changed)
        self.text = QPlainTextEdit()
        self.text.setMaximumHeight(110)
        self.expl = QPlainTextEdit()
        self.expl.setMaximumHeight(80)
        form.addRow(tr("col_document"), self.doc)
        form.addRow(tr("col_section"), self.section)
        form.addRow(tr("col_type"), self.qtype)
        form.addRow(tr("col_difficulty"), self.diff)
        form.addRow(tr("col_language"), self.lang)
        form.addRow(tr("qe_text") + " *", self.text)
        lay.addLayout(form)
        lay.addWidget(label(tr("qe_options"), "H2"))
        lay.addWidget(label(tr("qe_options_hint"), "Muted", wrap=True))
        grid = QGridLayout()
        self.opt_edits, self.opt_checks = [], []
        for i in range(MAX_OPTIONS):
            cb = QCheckBox(tr("qe_correct"))
            le = QLineEdit()
            le.setPlaceholderText(tr("qe_option_n", n=i + 1))
            grid.addWidget(le, i, 0)
            grid.addWidget(cb, i, 1)
            self.opt_edits.append(le)
            self.opt_checks.append(cb)
        lay.addLayout(grid)
        f2 = QFormLayout()
        f2.addRow(tr("qe_explanation"), self.expl)
        lay.addLayout(f2)
        self.source = label("", "Muted", wrap=True)
        lay.addWidget(self.source)
        bb = QDialogButtonBox()
        ok = bb.addButton(tr("save"), QDialogButtonBox.AcceptRole)
        ok.setProperty("primary", "true")
        bb.addButton(tr("cancel"), QDialogButtonBox.RejectRole)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        if qid:
            self._load(qid)
        else:
            if document_id:
                self.doc.setCurrentIndex(max(0, self.doc.findData(document_id)))
            self._load_sections()
            self.diff.setCurrentIndex(1)
            self._type_changed()

    def _version_for_doc(self, doc_id):
        pending = self.ctx.db.one("SELECT id FROM document_versions WHERE document_id = ? AND status = 'review'", (doc_id,))
        return pending["id"] if pending else self.ctx.documents.get(doc_id)["active_version_id"]

    def _load_sections(self):
        self.section.clear()
        did = self.doc.currentData()
        if did is None:
            return
        vid = self._version_for_doc(did)
        self.section.addItem("—", None)
        for s in self.ctx.documents.sections(vid):
            self.section.addItem(f"{s['number'] or '·'}  {s['text'][:90]}", s["id"])
        doc = self.ctx.documents.get(did)
        self.lang.setCurrentIndex(max(0, self.lang.findData(doc["language"])))

    def _type_changed(self):
        t = self.qtype.currentData()
        tf = t == QType.TRUEFALSE
        lab = TRUE_FALSE_LABELS[self.lang.currentData() or "ru"]
        for i, (le, cb) in enumerate(zip(self.opt_edits, self.opt_checks)):
            visible = not tf or i < 2
            le.setVisible(visible)
            cb.setVisible(visible)
            if tf and i < 2:
                le.setText(lab[i])
                le.setReadOnly(True)
            else:
                le.setReadOnly(False)
                if tf is False and le.text() in (TRUE_FALSE_LABELS["ru"] + TRUE_FALSE_LABELS["kk"]):
                    le.clear()

    def _load(self, qid):
        q = self.ctx.questions.get(qid)
        self.doc.setCurrentIndex(max(0, self.doc.findData(q["document_id"])))
        self.doc.setEnabled(False)
        self.section.clear()
        self.section.addItem("—", None)
        for s in self.ctx.documents.sections(q["version_id"]):
            self.section.addItem(f"{s['number'] or '·'}  {s['text'][:90]}", s["id"])
        self.section.setCurrentIndex(max(0, self.section.findData(q["section_id"])))
        self.qtype.setCurrentIndex(max(0, self.qtype.findData(q["qtype"])))
        self.diff.setCurrentIndex(max(0, self.diff.findData(q["difficulty"])))
        self.lang.setCurrentIndex(max(0, self.lang.findData(q["language"])))
        self.text.setPlainText(q["text"])
        self.expl.setPlainText(q["explanation"] or "")
        for i, o in enumerate(self.ctx.questions.options(qid)[:MAX_OPTIONS]):
            self.opt_edits[i].setText(o["text"])
            self.opt_checks[i].setChecked(bool(o["is_correct"]))
        self._type_changed()
        if q["source_text"]:
            self.source.setText(tr("qe_source", s=q["source_text"]))
        self._version_id = q["version_id"]

    def _collect(self) -> QuestionData:
        t = self.qtype.currentData()
        n = 2 if t == QType.TRUEFALSE else MAX_OPTIONS
        opts = [OptionData(le.text().strip(), cb.isChecked())
                for le, cb in list(zip(self.opt_edits, self.opt_checks))[:n] if le.text().strip()]
        sec_id = self.section.currentData()
        sec_num = ""
        if sec_id:
            r = self.ctx.db.one("SELECT number, text FROM document_sections WHERE id = ?", (sec_id,))
            sec_num = r["number"] or ""
        return QuestionData(qtype=t, text=self.text.toPlainText().strip(), options=opts,
                            explanation=self.expl.toPlainText().strip(), section_number=sec_num,
                            language=self.lang.currentData(), difficulty=self.diff.currentData())

    def _save(self):
        q = self._collect()
        errs = validate_question(q)
        if errs:
            warn(self, "\n".join(tr(e) for e in errs))
            return
        try:
            if self.qid:
                self.ctx.questions.update(self.qid, q)
                sec = self.section.currentData()
                self.ctx.db.execute("UPDATE questions SET section_id = ? WHERE id = ?", (sec, self.qid))
            else:
                did = self.doc.currentData()
                if did is None:
                    warn(self, tr("qe_need_doc"))
                    return
                sec = self.section.currentData()
                if sec:
                    q.source_text = self.ctx.db.scalar("SELECT text FROM document_sections WHERE id = ?", (sec,))[:1000]
                self.qid = self.ctx.questions.create(q, did, self._version_for_doc(did), sec, None,
                                                     status="draft", origin="manual")
                self.ctx.audit.log("question_add", "questions", self.qid)
        except Exception as e:
            error(self, e)
            return
        self.accept()
