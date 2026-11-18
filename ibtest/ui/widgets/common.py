"""Общие элементы интерфейса."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterable

from PySide6.QtCore import QDate, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ibtest.localization.i18n import tr, tr_error
from ibtest.ui import theme


def button(text: str, slot: Callable | None = None, primary: bool = False, danger: bool = False,
           tooltip: str = "") -> QPushButton:
    b = QPushButton(text)
    if primary:
        b.setProperty("primary", "true")
    if danger:
        b.setProperty("danger", "true")
    if tooltip:
        b.setToolTip(tooltip)
    if slot:
        b.clicked.connect(slot)
    b.setCursor(Qt.PointingHandCursor)
    return b


def label(text: str = "", obj: str | None = None, wrap: bool = False) -> QLabel:
    l = QLabel(text)
    if obj:
        l.setObjectName(obj)
    l.setWordWrap(wrap)
    return l


def card(layout_cls=QVBoxLayout) -> tuple[QFrame, Any]:
    f = QFrame()
    f.setObjectName("Card")
    lay = layout_cls(f)
    lay.setContentsMargins(16, 14, 16, 14)
    return f, lay


def hrow(*widgets, stretch_end: bool = False, spacing: int = 8) -> QHBoxLayout:
    h = QHBoxLayout()
    h.setSpacing(spacing)
    for w in widgets:
        if w is None:
            h.addStretch(1)
        elif isinstance(w, int):
            h.addSpacing(w)
        elif hasattr(w, "setParent") and not hasattr(w, "addWidget"):
            h.addWidget(w)
        else:
            h.addLayout(w)
    if stretch_end:
        h.addStretch(1)
    return h


class StatCard(QFrame):
    def __init__(self, title: str, value: str = "—"):
        super().__init__()
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        self.value = label(value, "StatValue")
        self.title = label(title, "StatLabel", wrap=True)
        lay.addWidget(self.value)
        lay.addWidget(self.title)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set(self, value: Any) -> None:
        self.value.setText(str(value))


def error(parent, exc_or_text, title: str | None = None) -> None:
    text = exc_or_text if isinstance(exc_or_text, str) else tr_error(exc_or_text)
    QMessageBox.critical(parent, title or tr("err_title"), text)


def info(parent, text: str, title: str | None = None) -> None:
    QMessageBox.information(parent, title or tr("info_title"), text)


def warn(parent, text: str, title: str | None = None) -> None:
    QMessageBox.warning(parent, title or tr("warn_title"), text)


def confirm(parent, text: str, title: str | None = None, danger: bool = False) -> bool:
    box = QMessageBox(QMessageBox.Warning if danger else QMessageBox.Question, title or tr("confirm_title"), text,
                      QMessageBox.Yes | QMessageBox.No, parent)
    yes = box.button(QMessageBox.Yes)
    yes.setText(tr("yes"))
    box.button(QMessageBox.No).setText(tr("no"))
    box.setDefaultButton(QMessageBox.No)
    box.exec()
    return box.clickedButton() is yes


def fmt_dt(s: str | None, with_time: bool = True) -> str:
    if not s:
        return ""
    try:
        d = datetime.fromisoformat(s)
        return d.strftime("%d.%m.%Y %H:%M" if with_time else "%d.%m.%Y")
    except ValueError:
        return s


def fmt_date_only(s: str | None) -> str:
    return fmt_dt(s, with_time=False)


def qdate_to_iso(d: QDate) -> str:
    return d.toString("yyyy-MM-dd")


def make_table(headers: list[str], stretch_col: int | None = None, multi: bool = False) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.ExtendedSelection if multi else QAbstractItemView.SingleSelection)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    t.setWordWrap(True)
    hh = t.horizontalHeader()
    hh.setSectionResizeMode(QHeaderView.ResizeToContents)
    if stretch_col is not None:
        hh.setSectionResizeMode(stretch_col, QHeaderView.Stretch)
    hh.setHighlightSections(False)
    return t


def fill_table(t: QTableWidget, rows: Iterable[list], keys: Iterable[Any] | None = None,
               colors: dict[int, Callable[[Any], str | None]] | None = None) -> None:
    rows = list(rows)
    keys = list(keys) if keys is not None else [None] * len(rows)
    t.setSortingEnabled(False)
    t.setRowCount(len(rows))
    for r, (row, key) in enumerate(zip(rows, keys)):
        for c, val in enumerate(row):
            it = QTableWidgetItem()
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                it.setData(Qt.DisplayRole, val)
            else:
                it.setText("" if val is None else str(val))
            if c == 0:
                it.setData(Qt.UserRole, key)
            if colors and c in colors:
                col = colors[c](val)
                if col:
                    it.setForeground(QBrush(QColor(col)))
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
            t.setItem(r, c, it)
    t.setSortingEnabled(True)
    t.resizeRowsToContents()


def selected_keys(t: QTableWidget) -> list:
    rows = sorted({i.row() for i in t.selectedIndexes()})
    return [t.item(r, 0).data(Qt.UserRole) for r in rows if t.item(r, 0) is not None]


def selected_key(t: QTableWidget):
    k = selected_keys(t)
    return k[0] if k else None


def status_color(val) -> str | None:
    for key, color in theme.STATUS_COLORS.items():
        if val == tr(f"st_{key}"):
            return color
    return None


def combo(items: list[tuple[str, Any]], current: Any = None) -> QComboBox:
    c = QComboBox()
    for text, data in items:
        c.addItem(text, data)
    if current is not None:
        idx = c.findData(current)
        if idx >= 0:
            c.setCurrentIndex(idx)
    return c


def set_combo(c: QComboBox, items: list[tuple[str, Any]], keep: bool = True) -> None:
    cur = c.currentData() if keep else None
    c.blockSignals(True)
    c.clear()
    for text, data in items:
        c.addItem(text, data)
    if cur is not None:
        idx = c.findData(cur)
        if idx >= 0:
            c.setCurrentIndex(idx)
    c.blockSignals(False)


class BarChart(QWidget):
    """Простая столбчатая диаграмма (QPainter), без внешних зависимостей."""

    def __init__(self, title: str = "", max_value: float | None = None, suffix: str = ""):
        super().__init__()
        self.title, self.max_value, self.suffix = title, max_value, suffix
        self.data: list[tuple[str, float]] = []
        self.setMinimumHeight(220)

    def set_data(self, data: list[tuple[str, float]]) -> None:
        self.data = [(str(a), float(b or 0)) for a, b in data]
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("white"))
        p.setPen(QColor(theme.NAVY))
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(10, 4, w - 20, 22), Qt.AlignLeft | Qt.AlignVCenter, self.title)
        f.setBold(False)
        f.setPointSizeF(8)
        p.setFont(f)
        if not self.data:
            p.setPen(QColor(theme.MUTED))
            p.drawText(self.rect(), Qt.AlignCenter, tr("no_data"))
            return
        left, top, bottom = 36, 34, 44
        ch = h - top - bottom
        cw = w - left - 12
        mx = self.max_value or max(v for _, v in self.data) or 1
        p.setPen(QPen(QColor(theme.LINE), 1))
        for i in range(5):
            y = top + ch * i / 4
            p.drawLine(left, int(y), w - 12, int(y))
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(0, y - 8, left - 4, 16), Qt.AlignRight | Qt.AlignVCenter, f"{mx * (4 - i) / 4:.0f}")
            p.setPen(QPen(QColor(theme.LINE), 1))
        n = len(self.data)
        slot = cw / n
        bw = min(48.0, slot * 0.6)
        for i, (lab, val) in enumerate(self.data):
            x = left + slot * i + (slot - bw) / 2
            bh = ch * (val / mx) if mx else 0
            p.fillRect(QRectF(x, top + ch - bh, bw, bh), QColor(theme.NAVY_LIGHT))
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(x - 20, top + ch - bh - 16, bw + 40, 14), Qt.AlignCenter, f"{val:g}{self.suffix}")
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(left + slot * i, top + ch + 4, slot, bottom - 6), int(Qt.AlignHCenter | Qt.AlignTop) | int(Qt.TextWordWrap),
                       lab if len(lab) <= 24 else lab[:22] + "…")


class PageBase(QWidget):
    """Базовая страница: заголовок, подзаголовок и вертикальная раскладка."""

    def __init__(self, ctx, title_key: str, subtitle_key: str | None = None):
        super().__init__()
        self.ctx = ctx
        self.title_key, self.subtitle_key = title_key, subtitle_key
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(24, 18, 24, 18)
        self.root.setSpacing(12)
        self.title_lbl = label(tr(title_key), "PageTitle")
        self.root.addWidget(self.title_lbl)
        if subtitle_key:
            self.sub_lbl = label(tr(subtitle_key), "Muted", wrap=True)
            self.root.addWidget(self.sub_lbl)

    def refresh(self) -> None:
        """Перечитать данные при открытии страницы."""
