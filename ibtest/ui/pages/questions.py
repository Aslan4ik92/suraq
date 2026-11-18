"""Раздел «База вопросов»."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QMenu

from ibtest.localization.i18n import tr
from ibtest.models.common import DIFFICULTIES, QStatus, QType
from ibtest.ui.dialogs.question_editor import QuestionEditor
from ibtest.ui.widgets.common import (PageBase, button, confirm, error, fill_table, fmt_dt, info, label, make_table,
                                      selected_keys, set_combo, status_color)


class QuestionsPage(PageBase):
    def __init__(self, ctx, navigate):
        super().__init__(ctx, "nav_questions", "q_subtitle")
        self.navigate = navigate
        bar = QHBoxLayout()
        self.doc = QComboBox()
        self.version = QComboBox()
        self.status = QComboBox()
        self.qtype = QComboBox()
        self.diff = QComboBox()
        self.lang = QComboBox()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("search_ph"))
        set_combo(self.status, [(tr("all_statuses"), None)] + [(tr(f"st_{s}"), s) for s in QStatus.ALL])
        set_combo(self.qtype, [(tr("all_types"), None)] + [(tr(f"qt_{t}"), t) for t in QType.ALL])
        set_combo(self.diff, [(tr("all_difficulties"), None)] + [(tr(f"diff_{d}"), d) for d in DIFFICULTIES])
        set_combo(self.lang, [(tr("all_languages"), None), (tr("lang_ru"), "ru"), (tr("lang_kk"), "kk")])
        self.doc.currentIndexChanged.connect(self._doc_changed)
        for w in (self.version, self.status, self.qtype, self.diff, self.lang):
            w.currentIndexChanged.connect(self._reload)
        self.search.textChanged.connect(self._reload)
        for w in (self.doc, self.version, self.status, self.qtype, self.diff, self.lang):
            bar.addWidget(w)
        bar.addWidget(self.search, 1)
        self.root.addLayout(bar)
        self.count = label("", "Muted")
        self.root.addWidget(self.count)
        self.table = make_table([tr("col_question"), tr("col_type"), tr("col_difficulty"), tr("col_section"),
                                 tr("col_document"), tr("col_version"), tr("col_language"), tr("col_status"),
                                 tr("col_origin"), tr("col_created")], stretch_col=0, multi=True)
        self.table.doubleClicked.connect(lambda _: self._edit())
        self.root.addWidget(self.table, 1)
        acts = QHBoxLayout()
        acts.addWidget(button(tr("q_add"), self._add, primary=True))
        acts.addWidget(button(tr("q_edit"), self._edit))
        st = button(tr("q_set_status"))
        m = QMenu(st)
        for s in (QStatus.REVIEW, QStatus.APPROVED, QStatus.REJECTED, QStatus.DRAFT):
            m.addAction(tr(f"st_{s}"), lambda s=s: self._set_status(s))
        st.setMenu(m)
        acts.addWidget(st)
        acts.addWidget(button(tr("q_to_review"), lambda: self.navigate("review")))
        acts.addStretch(1)
        acts.addWidget(button(tr("delete"), self._delete, danger=True))
        self.root.addLayout(acts)

    def refresh(self):
        docs = self.ctx.documents.list()
        set_combo(self.doc, [(tr("all_documents"), None)] + [(d["title"], d["id"]) for d in docs])
        self._doc_changed()

    def _doc_changed(self):
        did = self.doc.currentData()
        items = [(tr("all_versions"), None)]
        if did:
            items += [(f"{tr('col_version')} {v['version_no']} — {tr('st_' + v['status'])}", v["id"])
                      for v in self.ctx.documents.versions(did)]
        set_combo(self.version, items, keep=False)
        self._reload()

    def _reload(self):
        rows = self.ctx.questions.list(document_id=self.doc.currentData(), version_id=self.version.currentData(),
                                       status=self.status.currentData(), qtype=self.qtype.currentData(),
                                       difficulty=self.diff.currentData(), language=self.lang.currentData(),
                                       search=self.search.text().strip())
        fill_table(self.table, [[r["text"], tr(f"qt_{r['qtype']}"), tr(f"diff_{r['difficulty']}"),
                                 r["section_number"] or "", r["document_title"], r["version_no"],
                                 tr(f"lang_{r['language']}"), tr(f"st_{r['status']}"), tr(f"origin_{r['origin']}"),
                                 fmt_dt(r["created_at"])] for r in rows],
                   keys=[r["id"] for r in rows], colors={7: status_color})
        self.count.setText(tr("q_count", n=len(rows)))

    def _add(self):
        if not self.ctx.documents.list(include_archived=False):
            info(self, tr("q_need_document"))
            return
        if QuestionEditor(self, self.ctx, None, self.doc.currentData()).exec():
            self._reload()

    def _edit(self):
        ids = selected_keys(self.table)
        if not ids:
            info(self, tr("select_row"))
            return
        if QuestionEditor(self, self.ctx, ids[0]).exec():
            self._reload()

    def _set_status(self, status):
        ids = selected_keys(self.table)
        if not ids:
            info(self, tr("select_row"))
            return
        try:
            n = self.ctx.questions.set_status(ids, status)
        except Exception as e:
            error(self, e)
            return
        info(self, tr("q_status_changed", n=n))
        self._reload()

    def _delete(self):
        ids = selected_keys(self.table)
        if not ids or not confirm(self, tr("q_confirm_delete", n=len(ids)), danger=True):
            return
        try:
            self.ctx.questions.delete(ids)
        except Exception as e:
            error(self, e)
        self._reload()
