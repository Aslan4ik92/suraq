"""Отчёты: Excel (openpyxl), PDF (reportlab) и HTML для печати.

Для PDF используется шрифт DejaVu Sans из комплекта программы: он содержит
все казахские буквы (Ә Ғ Қ Ң Ө Ұ Ү Һ І).
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ibtest.config import paths
from ibtest.localization.i18n import tr

STATUS_KEYS = {True: "status_passed", False: "status_failed"}


@dataclass
class Report:
    title: str
    subtitle: str = ""
    summary: dict = field(default_factory=dict)
    results: list[dict] = field(default_factory=list)
    by_department: list[dict] = field(default_factory=list)
    by_document: list[dict] = field(default_factory=list)
    by_month: list[dict] = field(default_factory=list)
    employee: dict | None = None
    organization: str = ""


def _fmt_dt(s: str | None) -> tuple[str, str]:
    if not s:
        return "", ""
    try:
        d = datetime.fromisoformat(s)
        return d.strftime("%d.%m.%Y"), d.strftime("%H:%M")
    except ValueError:
        return s, ""


def _dur(sec) -> str:
    if not sec:
        return ""
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def result_rows(results: list[dict]) -> list[list]:
    rows = []
    for i, r in enumerate(results, start=1):
        d, t = _fmt_dt(r["started_at"])
        rows.append([i, r["employee_name"], r["department_name"], r.get("position") or "", d, t,
                     r.get("documents") or "", r["correct"], r["wrong"], f"{r['percent']:.1f}%",
                     tr(STATUS_KEYS[bool(r["passed"])])])
    return rows


def result_headers() -> list[str]:
    return [tr(k) for k in ("col_no", "col_fio", "col_department", "col_position", "col_date", "col_time",
                            "col_document_version", "col_correct", "col_wrong", "col_score", "col_status")]


# ---------------------------------------------------------------------- Excel
def export_excel(report: Report, path: Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    head_fill = PatternFill("solid", fgColor="1F3A5F")
    head_font = Font(bold=True, color="FFFFFF")
    thin = Side(style="thin", color="C9D1DC")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def table(ws, start_row: int, headers: list[str], rows: list[list], widths: list[int] | None = None):
        for c, h in enumerate(headers, start=1):
            cell = ws.cell(row=start_row, column=c, value=h)
            cell.fill, cell.font, cell.border = head_fill, head_font, border
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        for r_i, row in enumerate(rows, start=start_row + 1):
            for c, v in enumerate(row, start=1):
                cell = ws.cell(row=r_i, column=c, value=v)
                cell.border = border
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        if widths:
            for i, w in enumerate(widths, start=1):
                ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = ws.cell(row=start_row + 1, column=1)

    ws = wb.active
    ws.title = tr("rep_sheet_summary")[:31]
    ws["A1"] = report.title
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = report.subtitle
    if report.organization:
        ws["A3"] = report.organization
    row = 5
    s = report.summary
    for key, val in (("dash_tests", s.get("tests")), ("dash_employees", s.get("employees")),
                     ("an_passed", s.get("passed")), ("an_failed", s.get("failed")),
                     ("dash_avg", f"{s.get('avg_percent', 0)}%"), ("an_pass_rate", f"{s.get('pass_rate', 0)}%")):
        ws.cell(row=row, column=1, value=tr(key)).font = Font(bold=True)
        ws.cell(row=row, column=2, value=val)
        row += 1
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 18
    ws.cell(row=row + 1, column=1, value=tr("rep_generated") + " " + datetime.now().strftime("%d.%m.%Y %H:%M"))

    ws2 = wb.create_sheet(tr("rep_sheet_results")[:31])
    table(ws2, 1, result_headers(), result_rows(report.results), [5, 32, 24, 20, 12, 8, 40, 10, 10, 10, 12])

    if report.by_department:
        ws3 = wb.create_sheet(tr("rep_sheet_departments")[:31])
        table(ws3, 1, [tr("col_department"), tr("dash_tests"), tr("dash_employees"), tr("an_passed"), tr("dash_avg")],
              [[d["name"], d["tests"], d["employees"], d["passed"], d["avg_percent"]] for d in report.by_department],
              [36, 14, 14, 14, 16])
    if report.by_document:
        ws4 = wb.create_sheet(tr("rep_sheet_documents")[:31])
        table(ws4, 1, [tr("col_document"), tr("col_version"), tr("dash_tests"), tr("an_passed"), tr("an_correct_rate")],
              [[d["name"], d["version_no"], d["tests"], d["passed"], d["correct_rate"]] for d in report.by_document],
              [48, 10, 14, 14, 18])
    if report.by_month:
        ws5 = wb.create_sheet(tr("rep_sheet_months")[:31])
        table(ws5, 1, [tr("an_month"), tr("dash_tests"), tr("an_passed"), tr("dash_avg")],
              [[m["month"], m["tests"], m["passed"], m["avg_percent"]] for m in report.by_month], [14, 14, 14, 16])
        if len(report.by_month) >= 1:
            ch = BarChart()
            ch.title = tr("an_dynamics")
            ch.y_axis.title = "%"
            data = Reference(ws5, min_col=4, min_row=1, max_row=len(report.by_month) + 1)
            cats = Reference(ws5, min_col=1, min_row=2, max_row=len(report.by_month) + 1)
            ch.add_data(data, titles_from_data=True)
            ch.set_categories(cats)
            ch.height, ch.width = 8, 18
            ws5.add_chart(ch, "F2")
    if report.employee:
        ws6 = wb.create_sheet(tr("rep_sheet_employee")[:31])
        e = report.employee
        ws6["A1"], ws6["B1"] = tr("col_fio"), e.get("full_name")
        ws6["A2"], ws6["B2"] = tr("col_department"), e.get("department_name")
        ws6["A3"], ws6["B3"] = tr("col_position"), e.get("position") or ""
        ws6.column_dimensions["A"].width = 22
        ws6.column_dimensions["B"].width = 50
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


# ---------------------------------------------------------------------- PDF
_FONTS_READY = False


def _register_fonts():
    global _FONTS_READY
    if _FONTS_READY:
        return
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    fdir = paths.assets_dir() / "fonts"
    pdfmetrics.registerFont(TTFont("IBSans", str(fdir / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("IBSans-Bold", str(fdir / "DejaVuSans-Bold.ttf")))
    from reportlab.lib.fonts import addMapping
    addMapping("IBSans", 0, 0, "IBSans")
    addMapping("IBSans", 1, 0, "IBSans-Bold")
    _FONTS_READY = True


def export_pdf(report: Report, path: Path) -> Path:
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    _register_fonts()
    navy = colors.HexColor("#1F3A5F")
    st_title = ParagraphStyle("t", fontName="IBSans-Bold", fontSize=15, leading=19, textColor=navy, spaceAfter=4)
    st_sub = ParagraphStyle("s", fontName="IBSans", fontSize=9.5, leading=12, textColor=colors.HexColor("#555F6D"))
    st_h = ParagraphStyle("h", fontName="IBSans-Bold", fontSize=11.5, leading=15, textColor=navy, spaceBefore=10,
                          spaceAfter=6)
    st_cell = ParagraphStyle("c", fontName="IBSans", fontSize=7.8, leading=9.6)
    st_cell_h = ParagraphStyle("ch", fontName="IBSans-Bold", fontSize=7.8, leading=9.6, textColor=colors.white)

    def P(t, st=st_cell):
        return Paragraph(html.escape(str(t if t is not None else "")), st)

    def tbl(headers, rows, widths):
        data = [[P(h, st_cell_h) for h in headers]] + [[P(c) for c in r] for r in rows]
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), navy),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D1DC")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F5F8")]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return t

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pagesize = landscape(A4)
    doc = SimpleDocTemplate(str(path), pagesize=pagesize, leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm, title=report.title, author="ИБ ТЕСТ")
    story = [Paragraph(html.escape(report.title), st_title)]
    sub = " · ".join(x for x in (report.organization, report.subtitle,
                                tr("rep_generated") + " " + datetime.now().strftime("%d.%m.%Y %H:%M")) if x)
    story += [Paragraph(html.escape(sub), st_sub), Spacer(1, 6)]
    if report.employee:
        e = report.employee
        story.append(Paragraph(html.escape(f"{e.get('full_name')} — {e.get('department_name')}"
                                           + (f", {e['position']}" if e.get('position') else "")), st_h))
    s = report.summary
    story.append(tbl([tr("dash_tests"), tr("dash_employees"), tr("an_passed"), tr("an_failed"), tr("dash_avg"),
                      tr("an_pass_rate")],
                     [[s.get("tests", 0), s.get("employees", 0), s.get("passed", 0), s.get("failed", 0),
                       f"{s.get('avg_percent', 0)}%", f"{s.get('pass_rate', 0)}%"]], [42 * mm] * 6))
    if report.by_month and len(report.by_month) > 1:
        story.append(Paragraph(html.escape(tr("an_dynamics")), st_h))
        d = Drawing(240 * mm, 55 * mm)
        bc = VerticalBarChart()
        bc.x, bc.y, bc.height, bc.width = 12 * mm, 8 * mm, 42 * mm, 220 * mm
        bc.data = [[m["avg_percent"] or 0 for m in report.by_month]]
        bc.categoryAxis.categoryNames = [m["month"] for m in report.by_month]
        bc.categoryAxis.labels.fontName = bc.valueAxis.labels.fontName = "IBSans"
        bc.categoryAxis.labels.fontSize = bc.valueAxis.labels.fontSize = 7
        bc.valueAxis.valueMin, bc.valueAxis.valueMax, bc.valueAxis.valueStep = 0, 100, 20
        bc.bars[0].fillColor = navy
        d.add(bc)
        story.append(d)
    if report.by_department:
        story.append(Paragraph(html.escape(tr("an_by_department")), st_h))
        story.append(tbl([tr("col_department"), tr("dash_tests"), tr("dash_employees"), tr("an_passed"), tr("dash_avg")],
                         [[d["name"], d["tests"], d["employees"], d["passed"], f"{d['avg_percent']}%"]
                          for d in report.by_department], [110 * mm, 32 * mm, 32 * mm, 32 * mm, 32 * mm]))
    if report.by_document:
        story.append(Paragraph(html.escape(tr("an_by_document")), st_h))
        story.append(tbl([tr("col_document"), tr("col_version"), tr("dash_tests"), tr("an_passed"),
                          tr("an_correct_rate")],
                         [[d["name"], d["version_no"], d["tests"], d["passed"], f"{d['correct_rate']}%"]
                          for d in report.by_document], [130 * mm, 22 * mm, 30 * mm, 30 * mm, 36 * mm]))
    if report.results:
        story += [PageBreak() if len(story) > 6 else Spacer(1, 4),
                  Paragraph(html.escape(tr("rep_sheet_results")), st_h)]
        story.append(tbl(result_headers(), result_rows(report.results),
                         [9 * mm, 45 * mm, 34 * mm, 28 * mm, 18 * mm, 12 * mm, 60 * mm, 14 * mm, 14 * mm, 15 * mm,
                          20 * mm]))

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("IBSans", 7.5)
        canvas.setFillColor(colors.HexColor("#7A8594"))
        canvas.drawString(14 * mm, 8 * mm, "ИБ ТЕСТ")
        canvas.drawRightString(pagesize[0] - 14 * mm, 8 * mm, f"{doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return path


# ---------------------------------------------------------------------- HTML для печати
def to_html(report: Report) -> str:
    def esc(x):
        return html.escape(str(x if x is not None else ""))
    s = report.summary
    parts = [f"<h2 style='color:#1F3A5F'>{esc(report.title)}</h2>",
             f"<p style='color:#555'>{esc(report.organization)} {esc(report.subtitle)}</p>"]
    if report.employee:
        e = report.employee
        parts.append(f"<h3>{esc(e.get('full_name'))} — {esc(e.get('department_name'))}</h3>")
    parts.append("<table border='1' cellspacing='0' cellpadding='4' width='100%'><tr>" + "".join(
        f"<th bgcolor='#1F3A5F'><font color='white'>{esc(tr(k))}</font></th>" for k in
        ("dash_tests", "dash_employees", "an_passed", "an_failed", "dash_avg", "an_pass_rate")) + "</tr><tr>" + "".join(
        f"<td>{esc(v)}</td>" for v in (s.get("tests"), s.get("employees"), s.get("passed"), s.get("failed"),
                                       f"{s.get('avg_percent', 0)}%", f"{s.get('pass_rate', 0)}%")) + "</tr></table>")
    if report.results:
        parts.append(f"<h3>{esc(tr('rep_sheet_results'))}</h3><table border='1' cellspacing='0' cellpadding='3' "
                     "width='100%' style='font-size:9pt'><tr>" +
                     "".join(f"<th bgcolor='#1F3A5F'><font color='white'>{esc(h)}</font></th>" for h in result_headers())
                     + "</tr>" + "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>"
                                         for row in result_rows(report.results)) + "</table>")
    return "<html><body style='font-family:Segoe UI, Arial'>" + "".join(parts) + "</body></html>"
