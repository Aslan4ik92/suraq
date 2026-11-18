"""Раздел «Управление редакциями документов»."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QSplitter, QTextBrowser, QVBoxLayout, QWidget

from ibtest.localization.i18n import tr
from ibtest.services.documents import DocumentError
from ibtest.services.version_comparator.comparator import Change, SectionRef
from ibtest.ui import theme
from ibtest.ui.dialogs.document_import import DocumentImportDialog, DocumentTextDialog
from ibtest.ui.dialogs.generation import run_generation
from ibtest.ui.widgets.common import (PageBase, button, confirm, error, fill_table, fmt_dt, info, label, make_table,
                                      selected_key, set_combo, status_color)


class RevisionsPage(PageBase):
    def __init__(self, ctx, navigate):
        super().__init__(ctx, "nav_revisions", "rev_subtitle")
        self.navigate = navigate
        bar = QHBoxLayout()
        self.doc = QComboBox()
        self.doc.currentIndexChanged.connect(self._load_versions)
        bar.addWidget(label(tr("col_document")))
        bar.addWidget(self.doc, 1)
        bar.addWidget(button(tr("rev_upload"), self._upload, primary=True))
        self.root.addLayout(bar)
        self.versions = make_table([tr("col_version"), tr("col_status"), tr("col_file"), tr("col_number"),
                                    tr("col_doc_date"), tr("col_sections"), tr("col_questions"), tr("col_approved_q"),
                                    tr("col_analysis"), tr("col_loaded"), tr("col_activated")], stretch_col=2)
        self.versions.setMaximumHeight(210)
        self.versions.itemSelectionChanged.connect(self._load_changes)
        self.root.addWidget(self.versions)
        vacts = QHBoxLayout()
        self.btn_gen = button(tr("rev_generate"), self._generate, primary=True, tooltip=tr("rev_generate_tip"))
        self.btn_act = button(tr("rev_activate"), self._activate)
        self.btn_restore = button(tr("rev_restore"), self._restore)
        self.btn_discard = button(tr("rev_discard"), self._discard, danger=True)
        for b in (self.btn_gen, self.btn_act, self.btn_restore):
            vacts.addWidget(b)
        vacts.addWidget(button(tr("docs_view_text"), self._view_text))
        vacts.addWidget(button(tr("rev_to_review"), lambda: self.navigate("review")))
        vacts.addStretch(1)
        vacts.addWidget(self.btn_discard)
        self.root.addLayout(vacts)
        self.summary = label("", wrap=True)
        self.root.addWidget(self.summary)
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.filter = QComboBox()
        set_combo(self.filter, [(tr("rev_filter_changes"), "changes"), (tr("rev_filter_all"), "all")] +
                  [(tr(f"st_{t}"), t) for t in ("added", "modified", "removed", "manual", "unchanged")])
        self.filter.currentIndexChanged.connect(self._load_changes)
        ll.addWidget(self.filter)
        self.changes = make_table([tr("col_change"), tr("col_old_num"), tr("col_new_num"), tr("col_similarity"),
                                   tr("col_resolved")], stretch_col=0)
        self.changes.itemSelectionChanged.connect(self._show_diff)
        ll.addWidget(self.changes, 1)
        res = QHBoxLayout()
        self.btn_same = button(tr("rev_resolve_same"), lambda: self._resolve("same"))
        self.btn_diff = button(tr("rev_resolve_diff"), lambda: self._resolve("different"))
        res.addWidget(self.btn_same)
        res.addWidget(self.btn_diff)
        ll.addLayout(res)
        split.addWidget(left)
        self.diff = QTextBrowser()
        split.addWidget(self.diff)
        split.setSizes([380, 620])
        self.root.addWidget(split, 1)
        self._change_rows = []

    def select_document(self, doc_id):
        self.refresh()
        idx = self.doc.findData(doc_id)
        if idx >= 0:
            self.doc.setCurrentIndex(idx)

    def refresh(self):
        docs = self.ctx.documents.list()
        set_combo(self.doc, [(f"{d['title']} ({tr('st_' + d['status'])})", d["id"]) for d in docs])
        self._load_versions()

    def _version_rows(self):
        did = self.doc.currentData()
        return self.ctx.documents.versions(did) if did else []

    def _load_versions(self):
        rows = self._version_rows()
        fill_table(self.versions, [[r["version_no"], tr(f"st_{r['status']}"), r["file_name"], r["doc_number"] or "",
                                    r["doc_date"] or "", r["section_count"], r["question_count"], r["approved_count"],
                                    tr(f"anst_{r['analysis_state']}"), fmt_dt(r["created_at"]), fmt_dt(r["activated_at"])]
                                   for r in rows], keys=[r["id"] for r in rows], colors={1: status_color})
        if rows:
            self.versions.selectRow(0)
        else:
            self.changes.setRowCount(0)
            self.diff.clear()
            self.summary.setText("")
        self._buttons()

    def _cur_version(self):
        vid = selected_key(self.versions)
        return self.ctx.documents.version(vid) if vid else None

    def _buttons(self):
        v = self._cur_version()
        st = v["status"] if v else None
        self.btn_act.setEnabled(st == "review")
        self.btn_discard.setEnabled(st == "review")
        self.btn_restore.setEnabled(st == "superseded")
        self.btn_gen.setEnabled(st in ("review", "active"))

    def _load_changes(self):
        self._buttons()
        v = self._cur_version()
        if not v:
            return
        rows = [dict(r) for r in self.ctx.documents.changes(v["id"])]
        cnt = {}
        for r in rows:
            cnt[r["change_type"]] = cnt.get(r["change_type"], 0) + 1
        unresolved = sum(1 for r in rows if not r["resolved"])
        if rows:
            self.summary.setText(tr("rev_summary", added=cnt.get("added", 0), modified=cnt.get("modified", 0),
                                    removed=cnt.get("removed", 0), manual=cnt.get("manual", 0),
                                    unchanged=cnt.get("unchanged", 0), unresolved=unresolved))
        else:
            self.summary.setText(tr("rev_no_compare"))
        f = self.filter.currentData()
        if f == "changes":
            rows = [r for r in rows if r["change_type"] != "unchanged"]
        elif f != "all":
            rows = [r for r in rows if r["change_type"] == f]
        self._change_rows = rows
        fill_table(self.changes, [[tr(f"st_{r['change_type']}"), r["old_number"] or "", r["new_number"] or "",
                                   f"{(r['similarity'] or 0) * 100:.0f}%", tr("yes") if r["resolved"] else tr("no")]
                                  for r in rows], keys=[r["id"] for r in rows], colors={0: status_color})
        self.diff.clear()

    def _show_diff(self):
        cid = selected_key(self.changes)
        r = next((x for x in self._change_rows if x["id"] == cid), None)
        self.btn_same.setEnabled(bool(r and r["change_type"] == "manual" and not r["resolved"]))
        self.btn_diff.setEnabled(bool(r and r["change_type"] == "manual" and not r["resolved"]))
        if not r:
            self.diff.clear()
            return
        ch = Change(r["change_type"], SectionRef(0, r["old_number"] or "", r["old_text"] or "", "") if r["old_text"] else None,
                    SectionRef(0, r["new_number"] or "", r["new_text"] or "", "") if r["new_text"] else None,
                    r["similarity"] or 0)
        parts = []
        for tag, txt in ch.word_diff():
            t = html.escape(txt)
            if tag == "delete":
                parts.append(f"<span style='background:#FBE3E1;color:{theme.BAD};text-decoration:line-through'>{t}</span>")
            elif tag == "insert":
                parts.append(f"<span style='background:#DFF3E8;color:{theme.OK};font-weight:600'>{t}</span>")
            else:
                parts.append(t)
        old = html.escape(r["old_text"] or "—").replace("\n", "<br>")
        new = html.escape(r["new_text"] or "—").replace("\n", "<br>")
        self.diff.setHtml(
            f"<h3 style='color:{theme.NAVY}'>{html.escape(tr('st_' + r['change_type']))}</h3>"
            f"<p><b>{html.escape(tr('rev_diff'))}</b></p><p>{' '.join(parts)}</p><hr>"
            f"<table width='100%' cellpadding='6'><tr><th align='left'>{html.escape(tr('rev_old_text'))} "
            f"{html.escape(r['old_number'] or '')}</th><th align='left'>{html.escape(tr('rev_new_text'))} "
            f"{html.escape(r['new_number'] or '')}</th></tr><tr><td valign='top' bgcolor='#F8F9FB'>{old}</td>"
            f"<td valign='top' bgcolor='#F8F9FB'>{new}</td></tr></table>")

    def _upload(self):
        did = self.doc.currentData()
        if not did:
            info(self, tr("rev_choose_doc"))
            return
        doc = self.ctx.documents.get(did)
        dlg = DocumentImportDialog(self, self.ctx, "revision", doc)
        if dlg.exec() and dlg.revision:
            r = dlg.revision
            s = r.summary
            self._load_versions()
            msg = tr("rev_uploaded", added=s.get("added", 0), modified=s.get("modified", 0), removed=s.get("removed", 0),
                     manual=s.get("manual", 0), unchanged=s.get("unchanged", 0), ok=r.carried_approved,
                     review=r.carried_review)
            info(self, msg)
            if r.sections_to_generate and confirm(self, tr("rev_generate_now", n=len(r.sections_to_generate))):
                run_generation(self, self.ctx, r.version_id, r.sections_to_generate,
                               open_settings=lambda: self.navigate("settings"))
                self._load_versions()

    def _generate(self):
        v = self._cur_version()
        if not v:
            return
        if v["status"] == "review":
            ids = [c["new_section_id"] for c in self.ctx.documents.changes(v["id"])
                   if c["change_type"] in ("added", "modified", "manual") and c["new_section_id"]]
            if not ids:
                ids = None
        else:
            ids = None
        run_generation(self, self.ctx, v["id"], ids, open_settings=lambda: self.navigate("settings"))
        self._load_versions()

    def _activate(self):
        v = self._cur_version()
        if not v:
            return
        pending = self.ctx.db.scalar("SELECT COUNT(*) FROM questions WHERE version_id = ? AND status IN ('review','draft')",
                                     (v["id"],))
        text = tr("rev_confirm_activate", v=v["version_no"])
        if pending:
            text += "\n" + tr("rev_pending_q", n=pending)
        if not confirm(self, text):
            return
        try:
            self.ctx.documents.activate_version(v["id"])
        except DocumentError as e:
            if e.key in ("revision_unresolved", "revision_no_approved") and confirm(
                    self, tr(e.key, **e.kw) + "\n\n" + tr("rev_force"), danger=True):
                self.ctx.documents.activate_version(v["id"], force=True)
            else:
                error(self, e)
                return
        info(self, tr("rev_activated"))
        self.refresh()

    def _restore(self):
        v = self._cur_version()
        if not v or not confirm(self, tr("rev_confirm_restore", v=v["version_no"]), danger=True):
            return
        try:
            self.ctx.documents.restore_version(v["id"])
        except Exception as e:
            error(self, e)
            return
        self.refresh()

    def _discard(self):
        v = self._cur_version()
        if not v or not confirm(self, tr("rev_confirm_discard", v=v["version_no"]), danger=True):
            return
        try:
            self.ctx.documents.discard_revision(v["id"])
        except Exception as e:
            error(self, e)
            return
        self.refresh()

    def _resolve(self, resolution: str):
        cid = selected_key(self.changes)
        if cid is None:
            return
        try:
            self.ctx.documents.resolve_change(cid, resolution)
        except Exception as e:
            error(self, e)
        self._load_changes()

    def _view_text(self):
        v = self._cur_version()
        if v:
            DocumentTextDialog(self, f"{tr('col_version')} {v['version_no']}", v["raw_text"]).exec()
