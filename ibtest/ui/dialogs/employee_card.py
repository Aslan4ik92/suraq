"""Карточка сотрудника и просмотр отдельной попытки."""
from __future__ import annotations

import html

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QTabWidget, QTextBrowser, QVBoxLayout, QWidget

from ibtest.localization.i18n import tr
from ibtest.services.analytics.results import ResultFilter
from ibtest.services.report_generator.reports import Report
from ibtest.ui import theme
from ibtest.ui.dialogs.export import export_report, print_report
from ibtest.ui.widgets.common import (BarChart, button, fill_table, fmt_dt, label, make_table, selected_key,
                                      status_color)


class AttemptDialog(QDialog):
    def __init__(self, parent, ctx, session_id: int):
        super().__init__(parent)
        self.setWindowTitle(tr("att_title"))
        self.resize(900, 720)
        s = ctx.tests.result(session_id)
        lay = QVBoxLayout(self)
        ok = ctx.tests.verify_integrity(session_id)
        lay.addWidget(label(f"{s['employee_name']} · {s['department_name']} · {fmt_dt(s['started_at'])}", "H2"))
        lay.addWidget(label(tr("att_summary", correct=s["correct"], total=s["total"], p=s["percent"],
                               st=tr("status_passed" if s["passed"] else "status_failed"),
                               d=round((s["duration_sec"] or 0) / 60, 1)) + "  " +
                            (tr("att_integrity_ok") if ok else tr("att_integrity_bad")), wrap=True))
        view = QTextBrowser()
        e = html.escape
        parts = []
        for q in ctx.tests.review(session_id):
            right = q["selected"] == q["correct"]
            items = []
            for i, o in enumerate(q["options"]):
                mark = ""
                style = ""
                if o["correct"]:
                    style = f"color:{theme.OK};font-weight:600"
                    mark = "✔ "
                if i in q["selected"] and not o["correct"]:
                    style = f"color:{theme.BAD};font-weight:600"
                    mark = "✘ "
                elif i in q["selected"]:
                    mark = "✔ "
                items.append(f"<li style='{style}'>{mark}{e(o['text'])}{' ◀' if i in q['selected'] else ''}</li>")
            color = theme.OK if right else theme.BAD
            parts.append(f"<div style='border-left:4px solid {color};padding-left:8px;margin:10px 0'>"
                         f"<b>{q['order']}. {e(q['text'])}</b><br><span style='color:{theme.MUTED};font-size:9pt'>"
                         f"{e(q['document'])} · {e(tr('col_version'))} {q['version_no']} · {e(tr('col_section'))} "
                         f"{e(q['section'] or '—')}</span><ul>{''.join(items)}</ul>"
                         + ("" if q["selected"] else f"<i style='color:{theme.BAD}'>{e(tr('att_no_answer'))}</i>")
                         + f"<div style='color:{theme.MUTED}'>{e(q['explanation'] or '')}</div></div>")
        view.setHtml("".join(parts))
        lay.addWidget(view, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText(tr("close"))
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class EmployeeCardDialog(QDialog):
    def __init__(self, parent, ctx, employee_id: int):
        super().__init__(parent)
        self.ctx, self.employee_id = ctx, employee_id
        data = ctx.results.employee_card(employee_id)
        emp = data["employee"]
        self.setWindowTitle(tr("card_title"))
        self.resize(1000, 720)
        lay = QVBoxLayout(self)
        lay.addWidget(label(emp["full_name"], "PageTitle"))
        lay.addWidget(label(f"{tr('col_department')}: {emp['department_name']}    "
                            f"{tr('col_position')}: {emp['position'] or '—'}", "Muted"))
        tabs = QTabWidget()
        w1 = QWidget()
        l1 = QVBoxLayout(w1)
        self.att = make_table([tr("col_date"), tr("col_document_version"), tr("col_correct"), tr("col_wrong"),
                               tr("col_score"), tr("col_status"), tr("col_duration")], stretch_col=1)
        atts = data["attempts"]
        fill_table(self.att, [[fmt_dt(a["started_at"]), a["documents"], a["correct"], a["wrong"], f"{a['percent']:.1f}%",
                               tr("st_passed" if a["passed"] else "st_failed"),
                               f"{(a['duration_sec'] or 0) // 60}:{(a['duration_sec'] or 0) % 60:02d}"]
                              for a in reversed(atts)], keys=[a["session_id"] for a in reversed(atts)],
                   colors={5: status_color})
        self.att.doubleClicked.connect(self._open_attempt)
        l1.addWidget(self.att)
        l1.addLayout(_row(button(tr("card_open_attempt"), self._open_attempt)))
        tabs.addTab(w1, tr("card_attempts", n=len(atts)))
        w2 = QWidget()
        l2 = QVBoxLayout(w2)
        docs = make_table([tr("col_document"), tr("col_version"), tr("card_attempt_count"), tr("card_last_passed")],
                          stretch_col=0)
        fill_table(docs, [[d["document_title"], d["version_no"], d["attempts"], fmt_dt(d["last_passed"]) or "—"]
                          for d in data["documents"]])
        l2.addWidget(docs)
        tabs.addTab(w2, tr("card_documents"))
        w3 = QWidget()
        l3 = QVBoxLayout(w3)
        chart = BarChart(tr("card_dynamics"), max_value=100, suffix="%")
        chart.set_data([(fmt_dt(a["started_at"], with_time=False), a["percent"]) for a in atts[-15:]])
        l3.addWidget(chart)
        tabs.addTab(w3, tr("card_dynamics"))
        lay.addWidget(tabs, 1)
        f = ResultFilter(employee_id=employee_id, sort="date_asc")
        self.report = Report(tr("rep_employee_title"), subtitle=emp["full_name"], summary=ctx.results.summary(f),
                             results=ctx.results.list(f), by_document=ctx.results.by_document(f),
                             by_month=ctx.results.by_month(f), employee=emp)
        acts = _row(button(tr("export_excel"), lambda: export_report(self, ctx, self.report, "excel", "employee")),
                    button(tr("export_pdf"), lambda: export_report(self, ctx, self.report, "pdf", "employee")),
                    button(tr("print"), lambda: print_report(self, ctx, self.report)))
        acts.addStretch(1)
        close = button(tr("close"), self.reject)
        acts.addWidget(close)
        lay.addLayout(acts)

    def _open_attempt(self, *_):
        sid = selected_key(self.att)
        if sid:
            AttemptDialog(self, self.ctx, sid).exec()


def _row(*widgets) -> QHBoxLayout:
    h = QHBoxLayout()
    for w in widgets:
        h.addWidget(w)
    return h
