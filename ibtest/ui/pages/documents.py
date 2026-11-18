"""Раздел «Нормативные документы»."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QMenu

from ibtest.localization.i18n import tr
from ibtest.models.common import DocStatus
from ibtest.ui.dialogs.document_import import DocumentImportDialog, DocumentMetaDialog, DocumentTextDialog
from ibtest.ui.dialogs.generation import run_generation
from ibtest.ui.widgets.common import (PageBase, button, confirm, error, fill_table, fmt_date_only, fmt_dt, info,
                                      make_table, selected_key, set_combo, status_color)


def open_file(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", path])


class DocumentsPage(PageBase):
    def __init__(self, ctx, navigate):
        super().__init__(ctx, "nav_documents", "docs_subtitle")
        self.navigate = navigate
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("search_ph"))
        self.search.textChanged.connect(self.refresh)
        self.status = QComboBox()
        set_combo(self.status, [(tr("all_statuses"), None)] + [(tr(f"st_{s}"), s) for s in DocStatus.ALL])
        self.status.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.search, 2)
        bar.addWidget(self.status, 1)
        bar.addStretch(1)
        bar.addWidget(button(tr("docs_upload"), self._upload, primary=True))
        self.root.addLayout(bar)
        self.table = make_table([tr("col_document"), tr("col_number"), tr("col_doc_date"), tr("col_language"),
                                 tr("col_version"), tr("col_status"), tr("col_approved_q"), tr("col_review_q"),
                                 tr("col_updated")], stretch_col=0)
        self.table.doubleClicked.connect(lambda _: self._edit())
        self.root.addWidget(self.table, 1)
        acts = QHBoxLayout()
        acts.addWidget(button(tr("docs_analyze"), self._analyze, primary=True, tooltip=tr("docs_analyze_tip")))
        acts.addWidget(button(tr("docs_view_text"), self._view_text))
        acts.addWidget(button(tr("docs_open_original"), self._open_original))
        acts.addWidget(button(tr("docs_edit"), self._edit))
        acts.addWidget(button(tr("docs_revisions"), lambda: self.navigate("revisions", selected_key(self.table))))
        st_btn = button(tr("docs_change_status"))
        menu = QMenu(st_btn)
        for s in DocStatus.ALL:
            menu.addAction(tr(f"st_{s}"), lambda s=s: self._set_status(s))
        st_btn.setMenu(menu)
        acts.addWidget(st_btn)
        acts.addStretch(1)
        acts.addWidget(button(tr("delete"), self._delete, danger=True))
        self.root.addLayout(acts)

    def refresh(self):
        rows = self.ctx.documents.list(self.search.text().strip(), self.status.currentData())
        fill_table(self.table, [[r["title"], r["doc_number"] or "", fmt_date_only(r["doc_date"]),
                                 tr(f"lang_{r['language']}"), r["active_version_no"] or "", tr(f"st_{r['status']}"),
                                 r["approved_count"], r["review_count"], fmt_dt(r["updated_at"])] for r in rows],
                   keys=[r["id"] for r in rows], colors={5: status_color})

    def _current(self):
        did = selected_key(self.table)
        if did is None:
            info(self, tr("select_row"))
            return None
        return self.ctx.documents.get(did)

    def _upload(self):
        dlg = DocumentImportDialog(self, self.ctx, "new")
        if dlg.exec() and dlg.result_id:
            self.refresh()
            doc = self.ctx.documents.get(dlg.result_id)
            if confirm(self, tr("docs_analyze_now")):
                run_generation(self, self.ctx, doc["active_version_id"], None,
                               open_settings=lambda: self.navigate("settings"))
                self.refresh()

    def _analyze(self):
        doc = self._current()
        if not doc:
            return
        pending = self.ctx.db.one("SELECT id FROM document_versions WHERE document_id = ? AND status = 'review'",
                                  (doc["id"],))
        vid = doc["active_version_id"]
        if pending and confirm(self, tr("docs_analyze_pending")):
            vid = pending["id"]
        existing = self.ctx.db.scalar("SELECT COUNT(*) FROM questions WHERE version_id = ?", (vid,))
        if existing and not confirm(self, tr("docs_analyze_again", n=existing)):
            return
        run_generation(self, self.ctx, vid, None, open_settings=lambda: self.navigate("settings"))
        self.refresh()

    def _view_text(self):
        doc = self._current()
        if doc:
            v = self.ctx.documents.version(doc["active_version_id"])
            DocumentTextDialog(self, f"{doc['title']} — {tr('col_version')} {v['version_no']}", v["raw_text"]).exec()

    def _open_original(self):
        doc = self._current()
        if not doc:
            return
        v = self.ctx.documents.version(doc["active_version_id"])
        if not Path(v["stored_path"]).exists():
            error(self, tr("file_not_found"))
            return
        open_file(v["stored_path"])

    def _edit(self):
        doc = self._current()
        if doc and DocumentMetaDialog(self, self.ctx, doc).exec():
            self.refresh()

    def _set_status(self, status):
        doc = self._current()
        if not doc:
            return
        if status in (DocStatus.REVOKED, DocStatus.ARCHIVED) and not confirm(self, tr("docs_confirm_status",
                                                                                    st=tr(f"st_{status}"))):
            return
        try:
            self.ctx.documents.set_status(doc["id"], status)
        except Exception as e:
            error(self, e)
        self.refresh()

    def _delete(self):
        doc = self._current()
        if not doc or not confirm(self, tr("docs_confirm_delete", title=doc["title"]), danger=True):
            return
        try:
            self.ctx.documents.delete_document(doc["id"])
        except Exception as e:
            error(self, e)
        self.refresh()
