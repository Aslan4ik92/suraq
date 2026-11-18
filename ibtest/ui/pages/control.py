"""Раздел «Контроль тестирования»."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout

from ibtest.localization.i18n import tr
from ibtest.services.report_generator.reports import Report
from ibtest.ui.dialogs.employee_card import EmployeeCardDialog
from ibtest.ui.dialogs.export import export_report, print_report
from ibtest.ui.widgets.common import (PageBase, StatCard, button, fill_table, fmt_dt, info, label, make_table,
                                      selected_key, set_combo, status_color)

STATUSES = ("passed", "failed", "not_tested", "retest")


class ControlPage(PageBase):
    def __init__(self, ctx, navigate):
        super().__init__(ctx, "nav_control", "ctl_subtitle")
        bar = QHBoxLayout()
        self.doc = QComboBox()
        self.dept = QComboBox()
        self.status = QComboBox()
        set_combo(self.status, [(tr("all_statuses"), None)] + [(tr(f"st_{s}"), s) for s in STATUSES])
        for w in (self.doc, self.dept, self.status):
            w.currentIndexChanged.connect(self._reload)
        bar.addWidget(label(tr("col_document")))
        bar.addWidget(self.doc, 2)
        bar.addWidget(self.dept, 1)
        bar.addWidget(self.status, 1)
        self.root.addLayout(bar)
        cards = QHBoxLayout()
        self.cards = {s: StatCard(tr(f"st_{s}")) for s in STATUSES}
        for c in self.cards.values():
            cards.addWidget(c)
        self.root.addLayout(cards)
        self.hint = label(tr("ctl_hint"), "Muted", wrap=True)
        self.root.addWidget(self.hint)
        self.table = make_table([tr("col_fio"), tr("col_department"), tr("col_position"), tr("col_date"),
                                 tr("col_version"), tr("col_score"), tr("col_status")], stretch_col=0)
        self.table.doubleClicked.connect(lambda _: self._card())
        self.root.addWidget(self.table, 1)
        acts = QHBoxLayout()
        acts.addWidget(button(tr("res_card"), self._card))
        acts.addStretch(1)
        acts.addWidget(button(tr("export_excel"), lambda: self._export("excel")))
        acts.addWidget(button(tr("export_pdf"), lambda: self._export("pdf")))
        acts.addWidget(button(tr("print"), lambda: print_report(self, self.ctx, self._report())))
        self.root.addLayout(acts)
        self.rows = []

    def refresh(self):
        set_combo(self.doc, [(d["title"], d["id"]) for d in self.ctx.documents.list()
                             if d["active_version_id"]])
        set_combo(self.dept, [(tr("all_departments"), None)] + [(d["name"], d["id"])
                                                                 for d in self.ctx.employees.departments()])
        self._reload()

    def _reload(self):
        did = self.doc.currentData()
        if not did:
            self.table.setRowCount(0)
            return
        all_rows = self.ctx.results.control(did, self.dept.currentData())
        for s in STATUSES:
            self.cards[s].set(sum(1 for r in all_rows if r["status"] == s))
        st = self.status.currentData()
        self.rows = [r for r in all_rows if not st or r["status"] == st]
        fill_table(self.table, [[r["full_name"], r["department_name"], r["position"] or "", fmt_dt(r["date"]) or "—",
                                 r["version_no"] or "", f"{r['percent']:.1f}%" if r["percent"] is not None else "",
                                 tr(f"st_{r['status']}")] for r in self.rows],
                   keys=[r["employee_id"] for r in self.rows], colors={6: status_color})

    def _card(self):
        eid = selected_key(self.table)
        if eid is None:
            info(self, tr("select_row"))
            return
        EmployeeCardDialog(self, self.ctx, eid).exec()

    def _report(self) -> Report:
        rows = [{"employee_name": r["full_name"], "department_name": r["department_name"], "position": r["position"],
                 "started_at": r["date"], "documents": f"{self.doc.currentText()} ({tr('st_' + r['status'])})",
                 "correct": "", "wrong": "", "percent": r["percent"] or 0.0, "passed": r["status"] == "passed"}
                for r in self.rows]
        summary = {"tests": len(rows), "employees": len(rows),
                   "passed": sum(1 for r in self.rows if r["status"] == "passed"),
                   "failed": sum(1 for r in self.rows if r["status"] != "passed"), "avg_percent": "",
                   "pass_rate": round(100 * sum(1 for r in self.rows if r["status"] == "passed") / len(rows), 1) if rows else 0}
        return Report(tr("rep_control_title"), self.doc.currentText(), summary, rows)

    def _export(self, kind):
        export_report(self, self.ctx, self._report(), kind, "control")
