"""Раздел «База результатов»."""
from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QCheckBox, QComboBox, QDateEdit, QGridLayout, QHBoxLayout, QLineEdit

from ibtest.localization.i18n import tr
from ibtest.services.analytics.results import ResultFilter
from ibtest.services.report_generator.reports import Report
from ibtest.ui.dialogs.employee_card import AttemptDialog, EmployeeCardDialog
from ibtest.ui.dialogs.export import export_report, print_report
from ibtest.ui.widgets.common import (PageBase, button, fill_table, fmt_dt, info, label, make_table, qdate_to_iso,
                                      selected_key, set_combo, status_color)


class ResultsPage(PageBase):
    def __init__(self, ctx, navigate):
        super().__init__(ctx, "nav_results", "res_subtitle")
        g = QGridLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("res_search_fio"))
        self.dept = QComboBox()
        self.doc = QComboBox()
        self.version = QComboBox()
        self.status = QComboBox()
        set_combo(self.status, [(tr("all_statuses"), None), (tr("st_passed"), "passed"), (tr("st_failed"), "failed")])
        self.sort = QComboBox()
        set_combo(self.sort, [(tr("sort_date_desc"), "date_desc"), (tr("sort_date_asc"), "date_asc"),
                              (tr("sort_score_desc"), "score_desc"), (tr("sort_score_asc"), "score_asc")])
        self.use_dates = QCheckBox(tr("res_period"))
        self.d_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.d_to = QDateEdit(QDate.currentDate())
        for d in (self.d_from, self.d_to):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd.MM.yyyy")
        g.addWidget(self.search, 0, 0, 1, 2)
        g.addWidget(self.dept, 0, 2)
        g.addWidget(self.doc, 0, 3)
        g.addWidget(self.version, 0, 4)
        g.addWidget(self.status, 1, 0)
        g.addWidget(self.sort, 1, 1)
        g.addLayout(_h(self.use_dates, self.d_from, label("—"), self.d_to), 1, 2, 1, 2)
        self.root.addLayout(g)
        self.search.textChanged.connect(self._reload)
        self.doc.currentIndexChanged.connect(self._doc_changed)
        for w in (self.dept, self.version, self.status, self.sort):
            w.currentIndexChanged.connect(self._reload)
        self.use_dates.toggled.connect(self._reload)
        self.d_from.dateChanged.connect(self._reload)
        self.d_to.dateChanged.connect(self._reload)
        self.summary = label("", "Muted")
        self.root.addWidget(self.summary)
        self.table = make_table([tr("col_no"), tr("col_fio"), tr("col_department"), tr("col_position"), tr("col_date"),
                                 tr("col_time"), tr("col_document_version"), tr("col_correct"), tr("col_wrong"),
                                 tr("col_score"), tr("col_status")], stretch_col=6)
        self.table.doubleClicked.connect(lambda _: self._card())
        self.root.addWidget(self.table, 1)
        acts = QHBoxLayout()
        acts.addWidget(button(tr("res_card"), self._card, primary=True))
        acts.addWidget(button(tr("card_open_attempt"), self._attempt))
        acts.addStretch(1)
        acts.addWidget(button(tr("export_excel"), lambda: self._export("excel")))
        acts.addWidget(button(tr("export_pdf"), lambda: self._export("pdf")))
        acts.addWidget(button(tr("print"), lambda: print_report(self, self.ctx, self._report())))
        self.root.addLayout(acts)
        self.rows = []

    def refresh(self):
        set_combo(self.dept, [(tr("all_departments"), None)] + [(d["name"], d["id"])
                                                                 for d in self.ctx.employees.departments()])
        set_combo(self.doc, [(tr("all_documents"), None)] + [(d["title"], d["id"]) for d in self.ctx.documents.list()])
        self._doc_changed()

    def _doc_changed(self):
        did = self.doc.currentData()
        items = [(tr("all_versions"), None)]
        if did:
            items += [(f"{tr('col_version')} {v['version_no']}", v["id"]) for v in self.ctx.documents.versions(did)]
        set_combo(self.version, items, keep=False)
        self._reload()

    def _filter(self) -> ResultFilter:
        f = ResultFilter(search=self.search.text().strip(), department_id=self.dept.currentData(),
                         document_id=self.doc.currentData(), version_id=self.version.currentData(),
                         status=self.status.currentData(), sort=self.sort.currentData() or "date_desc")
        if self.use_dates.isChecked():
            f.date_from, f.date_to = qdate_to_iso(self.d_from.date()), qdate_to_iso(self.d_to.date())
        return f

    def _reload(self):
        f = self._filter()
        self.rows = self.ctx.results.list(f)
        data = []
        for i, r in enumerate(self.rows, start=1):
            dt = fmt_dt(r["started_at"])
            data.append([i, r["employee_name"], r["department_name"], r["position"] or "", dt[:10], dt[11:],
                         r["documents"], r["correct"], r["wrong"], f"{r['percent']:.1f}%",
                         tr("st_passed" if r["passed"] else "st_failed")])
        fill_table(self.table, data, keys=[r["session_id"] for r in self.rows], colors={10: status_color})
        s = self.ctx.results.summary(f)
        self.summary.setText(tr("res_summary", tests=s["tests"], emp=s["employees"], passed=s["passed"],
                                failed=s["failed"], avg=s["avg_percent"]))

    def _selected_row(self):
        sid = selected_key(self.table)
        return next((r for r in self.rows if r["session_id"] == sid), None)

    def _card(self):
        r = self._selected_row()
        if not r:
            info(self, tr("select_row"))
            return
        EmployeeCardDialog(self, self.ctx, r["employee_id"]).exec()

    def _attempt(self):
        r = self._selected_row()
        if r:
            AttemptDialog(self, self.ctx, r["session_id"]).exec()

    def _report(self) -> Report:
        f = self._filter()
        sub = []
        if f.date_from:
            sub.append(f"{self.d_from.date().toString('dd.MM.yyyy')} — {self.d_to.date().toString('dd.MM.yyyy')}")
        for c in (self.dept, self.doc, self.status):
            if c.currentData():
                sub.append(c.currentText())
        return Report(tr("rep_results_title"), " · ".join(sub), self.ctx.results.summary(f), self.ctx.results.list(f),
                      self.ctx.results.by_department(f), self.ctx.results.by_document(f), self.ctx.results.by_month(f))

    def _export(self, kind):
        export_report(self, self.ctx, self._report(), kind, "results")


def _h(*ws):
    h = QHBoxLayout()
    for w in ws:
        h.addWidget(w)
    return h
