"""Раздел «Аналитика»."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QComboBox, QDateEdit, QGridLayout, QHBoxLayout, QScrollArea, QTabWidget, QVBoxLayout, QWidget

from ibtest.localization.i18n import tr
from ibtest.services.analytics.results import ResultFilter, period_range
from ibtest.services.report_generator.reports import Report
from ibtest.ui.dialogs.export import export_report, print_report
from ibtest.ui.widgets.common import (BarChart, PageBase, StatCard, button, fill_table, label, make_table, qdate_to_iso,
                                      set_combo)


class AnalyticsPage(PageBase):
    def __init__(self, ctx, navigate):
        super().__init__(ctx, "nav_analytics", "an_subtitle")
        bar = QHBoxLayout()
        self.period = QComboBox()
        set_combo(self.period, [(tr("an_all_time"), "all"), (tr("an_day"), "day"), (tr("an_week"), "week"),
                                (tr("an_month_p"), "month"), (tr("an_custom"), "custom")])
        self.d_from = QDateEdit(QDate.currentDate().addMonths(-3))
        self.d_to = QDateEdit(QDate.currentDate())
        for d in (self.d_from, self.d_to):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd.MM.yyyy")
            d.dateChanged.connect(self.refresh_data)
        self.dept = QComboBox()
        self.doc = QComboBox()
        self.period.currentIndexChanged.connect(self._period_changed)
        self.dept.currentIndexChanged.connect(self.refresh_data)
        self.doc.currentIndexChanged.connect(self.refresh_data)
        for w in (self.period, self.d_from, self.d_to, self.dept, self.doc):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(button(tr("export_excel"), lambda: export_report(self, ctx, self._report(), "excel", "analytics")))
        bar.addWidget(button(tr("export_pdf"), lambda: export_report(self, ctx, self._report(), "pdf", "analytics")))
        bar.addWidget(button(tr("print"), lambda: print_report(self, ctx, self._report())))
        self.root.addLayout(bar)
        grid = QGridLayout()
        self.cards = {}
        for i, k in enumerate(("dash_tests", "dash_employees", "an_passed", "an_failed", "dash_avg", "an_pass_rate",
                               "an_not_tested")):
            self.cards[k] = StatCard(tr(k))
            grid.addWidget(self.cards[k], 0, i)
        self.root.addLayout(grid)
        tabs = QTabWidget()
        w1 = QWidget()
        l1 = QVBoxLayout(w1)
        self.ch_month = BarChart(tr("an_dynamics"), max_value=100, suffix="%")
        self.ch_dept = BarChart(tr("an_by_department"), max_value=100, suffix="%")
        l1.addWidget(self.ch_month)
        l1.addWidget(self.ch_dept)
        tabs.addTab(w1, tr("an_charts"))
        self.t_dept = make_table([tr("col_department"), tr("dash_tests"), tr("dash_employees"), tr("an_passed"),
                                  tr("dash_avg")], stretch_col=0)
        tabs.addTab(self.t_dept, tr("an_by_department"))
        self.t_doc = make_table([tr("col_document"), tr("col_version"), tr("dash_tests"), tr("an_passed"),
                                 tr("an_correct_rate")], stretch_col=0)
        tabs.addTab(self.t_doc, tr("an_by_document"))
        self.t_month = make_table([tr("an_month"), tr("dash_tests"), tr("an_passed"), tr("dash_avg")], stretch_col=0)
        tabs.addTab(self.t_month, tr("an_by_month"))
        self.t_hard = make_table([tr("col_question"), tr("col_document"), tr("an_shown"), tr("an_correct_rate")],
                                 stretch_col=0)
        tabs.addTab(self.t_hard, tr("an_hardest"))
        self.root.addWidget(tabs, 1)
        self._period_changed()

    def refresh(self):
        set_combo(self.dept, [(tr("all_departments"), None)] + [(d["name"], d["id"])
                                                                 for d in self.ctx.employees.departments()])
        set_combo(self.doc, [(tr("all_documents"), None)] + [(d["title"], d["id"]) for d in self.ctx.documents.list()])
        self.refresh_data()

    def _period_changed(self):
        custom = self.period.currentData() == "custom"
        self.d_from.setVisible(custom)
        self.d_to.setVisible(custom)
        self.refresh_data()

    def _filter(self) -> ResultFilter:
        f = ResultFilter(department_id=self.dept.currentData(), document_id=self.doc.currentData())
        p = self.period.currentData()
        if p in ("day", "week", "month"):
            f.date_from, f.date_to = period_range(p, date.today())
        elif p == "custom":
            f.date_from, f.date_to = qdate_to_iso(self.d_from.date()), qdate_to_iso(self.d_to.date())
        return f

    def refresh_data(self):
        if not hasattr(self, "cards"):
            return
        f = self._filter()
        s = self.ctx.results.summary(f)
        self.cards["dash_tests"].set(s["tests"])
        self.cards["dash_employees"].set(s["employees"])
        self.cards["an_passed"].set(s["passed"])
        self.cards["an_failed"].set(s["failed"])
        self.cards["dash_avg"].set(f"{s['avg_percent']}%")
        self.cards["an_pass_rate"].set(f"{s['pass_rate']}%")
        self.cards["an_not_tested"].set(self.ctx.results.not_tested_mandatory())
        dept = self.ctx.results.by_department(f)
        docs = self.ctx.results.by_document(f)
        months = self.ctx.results.by_month(f)
        self.ch_month.set_data([(m["month"], m["avg_percent"]) for m in months[-12:]])
        self.ch_dept.set_data([(d["name"], d["avg_percent"]) for d in dept[:12]])
        fill_table(self.t_dept, [[d["name"], d["tests"], d["employees"], d["passed"], d["avg_percent"]] for d in dept])
        fill_table(self.t_doc, [[d["name"], d["version_no"], d["tests"], d["passed"], d["correct_rate"]] for d in docs])
        fill_table(self.t_month, [[m["month"], m["tests"], m["passed"], m["avg_percent"]] for m in months])
        fill_table(self.t_hard, [[h["text"], h["document"], h["shown"], h["correct_rate"]]
                                 for h in self.ctx.results.hardest_questions(f)])

    def _report(self) -> Report:
        f = self._filter()
        sub = self.period.currentText()
        if f.date_from:
            sub += f": {f.date_from} — {f.date_to}"
        for c in (self.dept, self.doc):
            if c.currentData():
                sub += " · " + c.currentText()
        return Report(tr("rep_analytics_title"), sub, self.ctx.results.summary(f), self.ctx.results.list(f),
                      self.ctx.results.by_department(f), self.ctx.results.by_document(f), self.ctx.results.by_month(f))
