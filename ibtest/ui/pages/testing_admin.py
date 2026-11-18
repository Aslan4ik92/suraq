"""Раздел «Проведение тестирования»: профили тестирования и запуск режима сотрудника."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLineEdit,
                               QHeaderView, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout)
from PySide6.QtCore import Qt

from ibtest.localization.i18n import tr
from ibtest.ui.widgets.common import (PageBase, button, confirm, error, fill_table, info, label, make_table,
                                      selected_key)


class ProfileDialog(QDialog):
    def __init__(self, parent, ctx, pid=None):
        super().__init__(parent)
        self.ctx, self.pid = ctx, pid
        self.setWindowTitle(tr("prof_edit") if pid else tr("prof_new"))
        self.resize(760, 560)
        s = ctx.settings
        p = ctx.profiles.get(pid) if pid else None
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.name = QLineEdit(p["name"] if p else tr("prof_default_name"))
        self.count = QSpinBox()
        self.count.setRange(1, 300)
        self.count.setValue(p["question_count"] if p else int(s.get("default_question_count")))
        self.time = QSpinBox()
        self.time.setRange(0, 600)
        self.time.setSuffix(" " + tr("minutes"))
        self.time.setSpecialValueText(tr("prof_no_limit"))
        self.time.setValue(p["time_limit_min"] if p else int(s.get("default_time_limit_min")))
        self.pass_score = QSpinBox()
        self.pass_score.setRange(1, 100)
        self.pass_score.setSuffix(" %")
        self.pass_score.setValue(p["pass_score"] if p else int(s.get("default_pass_score")))
        self.lang = QComboBox()
        self.lang.addItem(tr("prof_lang_any"), None)
        self.lang.addItem(tr("lang_ru"), "ru")
        self.lang.addItem(tr("lang_kk"), "kk")
        if p:
            self.lang.setCurrentIndex(max(0, self.lang.findData(p["language"])))
        self.policy = QComboBox()
        self.policy.addItem(tr("prof_policy_block"), "block")
        self.policy.addItem(tr("prof_policy_shorten"), "shorten")
        if p:
            self.policy.setCurrentIndex(max(0, self.policy.findData(p["insufficient_policy"])))
        self.default = QCheckBox(tr("prof_is_default"))
        self.default.setChecked(bool(p["is_default"]) if p else not ctx.profiles.list())
        self.active = QCheckBox(tr("prof_is_active"))
        self.active.setChecked(bool(p["is_active"]) if p else True)
        f.addRow(tr("prof_name") + " *", self.name)
        f.addRow(tr("prof_count"), self.count)
        f.addRow(tr("prof_time"), self.time)
        f.addRow(tr("prof_pass"), self.pass_score)
        f.addRow(tr("prof_language"), self.lang)
        f.addRow(tr("prof_policy"), self.policy)
        f.addRow("", self.default)
        f.addRow("", self.active)
        lay.addLayout(f)
        lay.addWidget(label(tr("prof_docs_hint"), "Muted", wrap=True))
        self.docs = QTableWidget(0, 4)
        self.docs.setHorizontalHeaderLabels([tr("prof_use"), tr("col_document"), tr("prof_available"), tr("prof_q_count")])
        self.docs.horizontalHeader().setStretchLastSection(False)
        self.docs.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.docs.verticalHeader().setVisible(False)
        lay.addWidget(self.docs, 1)
        current = {d["document_id"]: d["question_count"] for d in ctx.profiles.documents(pid)} if pid else {}
        docs = [d for d in ctx.documents.list() if d["status"] in ("active", "revision_review", "pending_update")]
        self.docs.setRowCount(len(docs))
        self.spins = []
        for i, d in enumerate(docs):
            cb = QTableWidgetItem()
            cb.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            cb.setCheckState(Qt.Checked if d["id"] in current or (not pid and len(docs) == 1) else Qt.Unchecked)
            cb.setData(Qt.UserRole, d["id"])
            self.docs.setItem(i, 0, cb)
            self.docs.setItem(i, 1, QTableWidgetItem(d["title"]))
            avail = ctx.questions.usable_count(d["id"])
            self.docs.setItem(i, 2, QTableWidgetItem(str(avail)))
            sp = QSpinBox()
            sp.setRange(1, 300)
            sp.setValue(current.get(d["id"], self.count.value() if len(docs) == 1 else max(1, self.count.value() // max(1, len(docs)))))
            self.docs.setCellWidget(i, 3, sp)
            self.spins.append(sp)
        self.sum_lbl = label("", "Muted")
        lay.addWidget(self.sum_lbl)
        self.docs.itemChanged.connect(self._update_sum)
        for sp in self.spins:
            sp.valueChanged.connect(self._update_sum)
        self.count.valueChanged.connect(self._update_sum)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText(tr("save"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("cancel"))
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._update_sum()

    def _chosen(self):
        out = []
        for i in range(self.docs.rowCount()):
            it = self.docs.item(i, 0)
            if it.checkState() == Qt.Checked:
                out.append((it.data(Qt.UserRole), self.spins[i].value(), int(self.docs.item(i, 2).text())))
        return out

    def _update_sum(self, *_):
        ch = self._chosen()
        if len(ch) == 1:
            self.spins[[self.docs.item(i, 0).data(Qt.UserRole) for i in range(self.docs.rowCount())].index(ch[0][0])] \
                .setValue(self.count.value())
            ch = self._chosen()
        total = sum(c for _, c, _ in ch)
        lack = [c for c in ch if c[1] > c[2]]
        txt = tr("prof_sum", total=total, need=self.count.value())
        if lack:
            txt += "  ⚠ " + tr("prof_lack", n=len(lack))
        self.sum_lbl.setText(txt)

    def _save(self):
        ch = self._chosen()
        try:
            self.ctx.profiles.save(self.pid, self.name.text(), self.count.value(), self.time.value(),
                                   self.pass_score.value(), self.lang.currentData(), self.policy.currentData(),
                                   [(d, c) for d, c, _ in ch], self.default.isChecked(), self.active.isChecked())
        except Exception as e:
            error(self, e)
            return
        lack = [c for c in ch if c[1] > c[2]]
        if lack:
            info(self, tr("prof_saved_lack"))
        self.accept()


class TestingAdminPage(PageBase):
    def __init__(self, ctx, navigate, start_employee_mode):
        super().__init__(ctx, "nav_testing", "ta_subtitle")
        self.start_employee_mode = start_employee_mode
        r = QHBoxLayout()
        r.addWidget(button(tr("ta_start_mode"), self._start, primary=True, tooltip=tr("ta_start_tip")))
        r.addStretch(1)
        self.root.addLayout(r)
        self.root.addWidget(label(tr("ta_profiles"), "H2"))
        self.table = make_table([tr("prof_name"), tr("prof_count"), tr("prof_time"), tr("prof_pass"), tr("prof_language"),
                                 tr("prof_documents"), tr("prof_ready"), tr("col_status")], stretch_col=5)
        self.table.doubleClicked.connect(lambda _: self._edit())
        self.table.itemSelectionChanged.connect(self._readiness)
        self.root.addWidget(self.table, 1)
        a = QHBoxLayout()
        a.addWidget(button(tr("prof_new"), self._new, primary=True))
        a.addWidget(button(tr("prof_edit"), self._edit))
        a.addStretch(1)
        a.addWidget(button(tr("delete"), self._delete, danger=True))
        self.root.addLayout(a)
        self.ready = label("", wrap=True)
        self.root.addWidget(self.ready)

    def refresh(self):
        rows = self.ctx.profiles.list()
        data = []
        for p in rows:
            rd = self.ctx.profiles.readiness(p["id"])
            ok = all(x["available"] >= x["need"] for x in rd) and rd
            data.append([p["name"] + (" ★" if p["is_default"] else ""), p["question_count"],
                         p["time_limit_min"] or tr("prof_no_limit"), f"{p['pass_score']}%",
                         tr(f"lang_{p['language']}") if p["language"] else tr("prof_lang_any"),
                         ", ".join(f"{x['title']} ({x['need']})" for x in rd),
                         tr("yes") if ok else tr("no"), tr("st_active") if p["is_active"] else tr("st_archived")])
        fill_table(self.table, data, keys=[p["id"] for p in rows])
        self._readiness()

    def _readiness(self):
        pid = selected_key(self.table)
        if not pid:
            self.ready.setText(tr("ta_no_profiles") if not self.table.rowCount() else "")
            return
        lines = []
        for x in self.ctx.profiles.readiness(pid):
            mark = "✔" if x["available"] >= x["need"] else "⚠"
            lines.append(f"{mark} {x['title']}: " + tr("ta_ready_line", need=x["need"], avail=x["available"]))
        self.ready.setText("\n".join(lines))

    def _new(self):
        if not self.ctx.documents.list(include_archived=False):
            info(self, tr("q_need_document"))
            return
        if ProfileDialog(self, self.ctx).exec():
            self.refresh()

    def _edit(self):
        pid = selected_key(self.table)
        if pid and ProfileDialog(self, self.ctx, pid).exec():
            self.refresh()

    def _delete(self):
        pid = selected_key(self.table)
        if pid and confirm(self, tr("prof_confirm_delete"), danger=True):
            self.ctx.profiles.delete(pid)
            self.refresh()

    def _start(self):
        profiles = self.ctx.profiles.list(active_only=True)
        if not profiles:
            info(self, tr("ta_no_profiles"))
            return
        bad = [p["name"] for p in profiles if p["insufficient_policy"] == "block" and
               any(x["available"] < x["need"] for x in self.ctx.profiles.readiness(p["id"]))]
        if bad and not confirm(self, tr("ta_not_ready", names=", ".join(bad))):
            return
        self.start_employee_mode()
