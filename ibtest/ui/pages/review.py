"""Раздел «Проверка и утверждение вопросов»."""
from __future__ import annotations

import html
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QInputDialog, QSplitter, QTextBrowser, QVBoxLayout, QWidget

from ibtest.localization.i18n import tr
from ibtest.models.common import QStatus
from ibtest.services.ai_engine.llm import ModelLoadError, ModelNotConfigured
from ibtest.ui import theme
from ibtest.ui.dialogs.question_editor import QuestionEditor
from ibtest.ui.widgets.common import (PageBase, button, confirm, error, fill_table, info, label, make_table,
                                      selected_keys, set_combo)
from ibtest.ui.workers import run_with_progress


class ReviewPage(PageBase):
    def __init__(self, ctx, navigate):
        super().__init__(ctx, "nav_review", "rev_q_subtitle")
        self.navigate = navigate
        bar = QHBoxLayout()
        self.doc = QComboBox()
        self.doc.currentIndexChanged.connect(self._reload)
        self.status = QComboBox()
        set_combo(self.status, [(tr("rq_pending"), "pending"), (tr("st_review"), QStatus.REVIEW),
                                (tr("st_draft"), QStatus.DRAFT), (tr("st_rejected"), QStatus.REJECTED)])
        self.status.currentIndexChanged.connect(self._reload)
        bar.addWidget(self.doc, 2)
        bar.addWidget(self.status, 1)
        self.count = label("", "Muted")
        bar.addWidget(self.count)
        bar.addStretch(1)
        self.root.addLayout(bar)
        split = QSplitter(Qt.Horizontal)
        self.table = make_table([tr("col_question"), tr("col_section"), tr("col_type"), tr("col_note")],
                                stretch_col=0, multi=True)
        self.table.itemSelectionChanged.connect(self._show)
        split.addWidget(self.table)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.view = QTextBrowser()
        rl.addWidget(self.view, 1)
        a1 = QHBoxLayout()
        a1.addWidget(button(tr("rq_approve") + "  (Ctrl+Enter)", self._approve, primary=True))
        a1.addWidget(button(tr("rq_reject"), self._reject, danger=True))
        a1.addWidget(button(tr("q_edit"), self._edit))
        a1.addWidget(button(tr("rq_reanalyze"), self._reanalyze, tooltip=tr("rq_reanalyze_tip")))
        rl.addLayout(a1)
        a2 = QHBoxLayout()
        a2.addWidget(button(tr("rq_approve_selected"), self._approve))
        a2.addWidget(button(tr("rq_approve_all"), self._approve_all))
        a2.addStretch(1)
        a2.addWidget(button(tr("delete"), self._delete, danger=True))
        rl.addLayout(a2)
        split.addWidget(right)
        split.setSizes([460, 640])
        self.root.addWidget(split, 1)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._approve)
        QShortcut(QKeySequence("Ctrl+Delete"), self, activated=self._reject)
        self.rows = []

    def refresh(self):
        docs = self.ctx.documents.list()
        set_combo(self.doc, [(tr("all_documents"), None)] + [(d["title"], d["id"]) for d in docs])
        self._reload()

    def _reload(self):
        st = self.status.currentData()
        statuses = (QStatus.REVIEW, QStatus.DRAFT) if st == "pending" else (st,)
        self.rows = self.ctx.questions.list(document_id=self.doc.currentData(), statuses=statuses)
        fill_table(self.table, [[r["text"], r["section_number"] or "", tr(f"qt_{r['qtype']}"),
                                 tr(r["review_note"]) if r["review_note"] else ""] for r in self.rows],
                   keys=[r["id"] for r in self.rows])
        self.count.setText(tr("q_count", n=len(self.rows)))
        if self.rows:
            self.table.selectRow(0)
        else:
            self.view.setHtml(f"<p style='color:{theme.MUTED}'>{html.escape(tr('rq_empty'))}</p>")

    def _show(self):
        ids = selected_keys(self.table)
        if not ids:
            return
        q = self.ctx.questions.get(ids[0])
        opts = self.ctx.questions.options(ids[0])
        e = html.escape
        o_html = "".join(
            f"<li style='margin:4px 0;{'color:' + theme.OK + ';font-weight:600' if o['is_correct'] else ''}'>"
            f"{'✔ ' if o['is_correct'] else ''}{e(o['text'])}</li>" for o in opts)
        sec = q["section_text"] or ""
        src = q["source_text"] or ""
        sec_html = e(sec).replace("\n", "<br>")
        if src:
            # Подсветка цитаты в тексте пункта (если найдена дословно).
            esc_src = e(src)
            idx = sec_html.lower().find(esc_src.lower()[:60])
            if idx >= 0:
                end = idx + len(esc_src)
                sec_html = sec_html[:idx] + f"<span style='background:#FFF1C2'>{sec_html[idx:end]}</span>" + sec_html[end:]
        hist = self.ctx.questions.approvals(ids[0])
        h_html = "".join(f"<div style='color:{theme.MUTED};font-size:9pt'>{e(a['created_at'][:16])} · "
                         f"{e(a['username'] or 'AI')} · {e(tr('qa_' + a['action']))}"
                         f"{' — ' + e(a['comment']) if a['comment'] else ''}</div>" for a in hist[-6:])
        note = f"<p style='color:{theme.WARN}'><b>{e(tr(q['review_note']))}</b></p>" if q["review_note"] else ""
        self.view.setHtml(
            f"<p style='color:{theme.MUTED}'>{e(q['document_title'])} · {e(tr('col_version'))} {q['version_no']} · "
            f"{e(tr('col_section'))} {e(q['section_number'] or '—')} · {e(tr('qt_' + q['qtype']))} · "
            f"{e(tr('diff_' + q['difficulty']))} · {e(tr('lang_' + q['language']))}</p>{note}"
            f"<h3 style='color:{theme.NAVY}'>{e(q['text'])}</h3><ol>{o_html}</ol>"
            f"<p><b>{e(tr('qe_explanation'))}:</b> {e(q['explanation'] or '—')}</p><hr>"
            f"<p><b>{e(tr('rq_source_section'))} {e(q['section_number'] or '')}</b></p>"
            f"<div style='background:#F6F8FB;padding:8px'>{sec_html or e(src) or '—'}</div>"
            f"<p><b>{e(tr('rq_quote'))}:</b> <i>{e(src) or '—'}</i></p><hr>{h_html}")

    def _approve(self):
        ids = selected_keys(self.table)
        if not ids:
            return
        try:
            self.ctx.questions.set_status(ids, QStatus.APPROVED)
        except Exception as e:
            error(self, e)
        self._reload_keep()

    def _approve_all(self):
        ids = [r["id"] for r in self.rows]
        if not ids or not confirm(self, tr("rq_confirm_all", n=len(ids))):
            return
        try:
            n = self.ctx.questions.set_status(ids, QStatus.APPROVED)
        except Exception as e:
            error(self, e)
            n = 0
        info(self, tr("q_status_changed", n=n))
        self._reload()

    def _reject(self):
        ids = selected_keys(self.table)
        if not ids:
            return
        reason, ok = QInputDialog.getText(self, tr("rq_reject"), tr("rq_reject_reason"))
        if not ok:
            return
        self.ctx.questions.set_status(ids, QStatus.REJECTED, reason.strip())
        self._reload_keep()

    def _delete(self):
        ids = selected_keys(self.table)
        if ids and confirm(self, tr("q_confirm_delete", n=len(ids)), danger=True):
            self.ctx.questions.delete(ids)
            self._reload_keep()

    def _edit(self):
        ids = selected_keys(self.table)
        if ids and QuestionEditor(self, self.ctx, ids[0]).exec():
            self._reload_keep()

    def _reanalyze(self):
        ids = selected_keys(self.table)
        if not ids:
            return
        if not self.ctx.settings.get("ai_model_path"):
            if confirm(self, tr("gen_no_model")):
                self.navigate("settings")
            return

        def job(progress, cancel):
            progress(0, 0, "model_loading")
            return self.ctx.make_generator().reanalyze(ids[0])

        res, err = run_with_progress(self, tr("rq_reanalyze"), job, cancellable=False)
        if err:
            error(self, tr("gen_model_error") + "\n" + str(err) if isinstance(err, (ModelNotConfigured, ModelLoadError))
                  else err)
            return
        ok, comment = res
        info(self, tr("rq_reanalyze_ok") if ok else tr("rq_reanalyze_fixed", c=comment or "—"))
        self._reload_keep()

    def _reload_keep(self):
        row = max(0, self.table.currentRow())
        self._reload()
        if self.table.rowCount():
            self.table.selectRow(min(row, self.table.rowCount() - 1))
