"""Главная страница: сводные показатели."""
from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout

from ibtest.localization.i18n import tr
from ibtest.ui.widgets.common import PageBase, StatCard, card, fill_table, fmt_dt, label, make_table, status_color


class HomePage(PageBase):
    def __init__(self, ctx, navigate):
        super().__init__(ctx, "nav_home", "home_subtitle")
        self.navigate = navigate
        grid = QGridLayout()
        grid.setSpacing(12)
        self.cards = {}
        keys = ["dash_documents", "dash_active_docs", "dash_approved_q", "dash_employees", "dash_tests", "dash_avg"]
        for i, k in enumerate(keys):
            c = StatCard(tr(k))
            self.cards[k] = c
            grid.addWidget(c, i // 3, i % 3)
        self.root.addLayout(grid)
        self.alert = label("", wrap=True)
        self.root.addWidget(self.alert)
        row = QHBoxLayout()
        c1, l1 = card()
        l1.addWidget(label(tr("home_recent"), "H2"))
        self.recent = make_table([tr("col_date"), tr("col_fio"), tr("col_department"), tr("col_score"),
                                  tr("col_status")], stretch_col=1)
        l1.addWidget(self.recent)
        row.addWidget(c1, 3)
        c2, l2 = card()
        l2.addWidget(label(tr("home_pending_docs"), "H2"))
        self.pending_docs = make_table([tr("col_document"), tr("col_status")], stretch_col=0)
        self.pending_docs.doubleClicked.connect(lambda _: self.navigate("revisions"))
        l2.addWidget(self.pending_docs)
        self.pending_q = label("", wrap=True)
        l2.addWidget(self.pending_q)
        row.addWidget(c2, 2)
        self.root.addLayout(row, 1)

    def refresh(self):
        d = self.ctx.results.dashboard()
        self.cards["dash_documents"].set(d["documents"])
        self.cards["dash_active_docs"].set(d["active_documents"])
        self.cards["dash_approved_q"].set(d["approved_questions"])
        self.cards["dash_employees"].set(d["tested_employees"])
        self.cards["dash_tests"].set(d["tests"])
        self.cards["dash_avg"].set(f"{d['avg_percent']}%")
        fill_table(self.recent, [[fmt_dt(r["started_at"]), r["employee_name"], r["department_name"],
                                  f"{r['percent']:.1f}%", tr("st_passed" if r["passed"] else "st_failed")]
                                 for r in d["recent"]], colors={4: status_color})
        fill_table(self.pending_docs, [[x["title"], tr(f"st_{x['status']}")] for x in d["pending_documents"]],
                   keys=[x["id"] for x in d["pending_documents"]], colors={1: status_color})
        self.pending_q.setText(tr("home_pending_q", n=d["pending_questions"]))
        msgs = []
        if not self.ctx.settings.get("ai_model_path"):
            msgs.append(tr("home_no_model"))
        if not self.ctx.profiles.list(active_only=True):
            msgs.append(tr("home_no_profile"))
        self.alert.setText("\n".join("⚠ " + m for m in msgs))
        self.alert.setVisible(bool(msgs))
