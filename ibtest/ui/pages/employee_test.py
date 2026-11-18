"""Интерфейс сотрудника: ввод данных, прохождение теста, результат."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QProgressBar, QPushButton, QRadioButton, QScrollArea, QStackedWidget,
                               QVBoxLayout, QWidget)

from ibtest.localization.i18n import tr
from ibtest.services.employees import EmployeeError
from ibtest.services.test_engine.engine import TestBuildError
from ibtest.ui import theme
from ibtest.ui.widgets.common import button, card, confirm, error, label, warn


class EmployeeTestPage(QWidget):
    """Три экрана: анкета → вопросы → итог."""
    admin_requested = Signal()
    session_state = Signal(bool)  # True — идёт тестирование (вход администратора блокируется)

    def __init__(self, ctx, kiosk: bool = False):
        super().__init__()
        self.ctx = ctx
        self.kiosk = kiosk
        self.session_id: int | None = None
        self.qs = []
        self.answers: dict[int, list[int]] = {}
        self.idx = 0
        self.stack = QStackedWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)
        self._build_start()
        self._build_quiz()
        self._build_result()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    # ------------------------------------------------------------ анкета
    def _build_start(self):
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(40, 30, 40, 30)
        outer.addStretch(1)
        box, lay = card()
        box.setMaximumWidth(620)
        self.start_title = label(tr("emp_title"), "PageTitle")
        self.start_sub = label(tr("emp_subtitle"), "Muted", wrap=True)
        lay.addWidget(self.start_title)
        lay.addWidget(self.start_sub)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setVerticalSpacing(10)
        self.fio = QLineEdit()
        self.fio.setPlaceholderText(tr("emp_fio_ph"))
        self.dept = QComboBox()
        self.dept.setEditable(True)
        self.dept.setInsertPolicy(QComboBox.NoInsert)
        self.dept.lineEdit().setPlaceholderText(tr("emp_dept_ph"))
        self.position = QLineEdit()
        self.position.setPlaceholderText(tr("optional"))
        self.profile = QComboBox()
        self.lbl_fio, self.lbl_dept = QLabel(tr("emp_fio") + " *"), QLabel(tr("emp_dept") + " *")
        self.lbl_pos, self.lbl_prof = QLabel(tr("emp_position")), QLabel(tr("emp_profile"))
        form.addRow(self.lbl_fio, self.fio)
        form.addRow(self.lbl_dept, self.dept)
        form.addRow(self.lbl_pos, self.position)
        form.addRow(self.lbl_prof, self.profile)
        lay.addLayout(form)
        self.profile_info = label("", "Muted", wrap=True)
        lay.addWidget(self.profile_info)
        self.profile.currentIndexChanged.connect(self._profile_info)
        self.start_btn = button(tr("emp_start"), self._start, primary=True)
        self.start_btn.setMinimumHeight(38)
        lay.addSpacing(6)
        lay.addWidget(self.start_btn)
        self.fio.returnPressed.connect(self._start)
        h = QHBoxLayout()
        h.addStretch(1)
        h.addWidget(box)
        h.addStretch(1)
        outer.addLayout(h)
        outer.addStretch(2)
        if self.kiosk:
            adm = button(tr("emp_admin_login"), self.admin_requested.emit)
            adm.setFlat(True)
            hr = QHBoxLayout()
            hr.addStretch(1)
            hr.addWidget(adm)
            outer.addLayout(hr)
        self.stack.addWidget(w)

    def refresh(self):
        if self.session_id is not None:
            return
        depts = [d["name"] for d in self.ctx.employees.departments(active_only=True)]
        cur = self.dept.currentText()
        self.dept.clear()
        self.dept.addItems(depts)
        self.dept.setCurrentText(cur)
        self.profile.clear()
        for p in self.ctx.profiles.list(active_only=True):
            self.profile.addItem(p["name"], p["id"])
        self.lbl_prof.setVisible(self.profile.count() > 1)
        self.profile.setVisible(self.profile.count() > 1)
        self.start_btn.setEnabled(self.profile.count() > 0)
        self._profile_info()

    def _profile_info(self):
        pid = self.profile.currentData()
        if pid is None:
            self.profile_info.setText(tr("emp_no_profiles"))
            return
        p = self.ctx.profiles.get(pid)
        t = tr("emp_profile_info", n=p["question_count"], pass_score=p["pass_score"])
        if p["time_limit_min"]:
            t += " " + tr("emp_profile_time", m=p["time_limit_min"])
        docs = ", ".join(d["title"] for d in self.ctx.profiles.documents(pid))
        self.profile_info.setText(t + "\n" + tr("emp_profile_docs", docs=docs))

    def _start(self):
        fio = " ".join(self.fio.text().split())
        dept = " ".join(self.dept.currentText().split())
        if len(fio.split()) < 2:
            warn(self, tr("emp_err_fio"))
            self.fio.setFocus()
            return
        if not dept:
            warn(self, tr("emp_err_dept"))
            self.dept.setFocus()
            return
        pid = self.profile.currentData()
        if pid is None:
            warn(self, tr("emp_no_profiles"))
            return
        try:
            emp = self.ctx.employees.find_or_create(fio, dept, self.position.text())
            sid = self.ctx.tests.build(pid, emp)
        except TestBuildError as e:
            if e.key == "not_enough_questions":
                warn(self, tr("emp_not_ready"))
                self.ctx.audit.log("test_build_failed", "test_profiles", pid,
                                   {"reason": e.key, "items": e.kw.get("items")})
            else:
                error(self, e)
            return
        except EmployeeError as e:
            error(self, e)
            return
        self.session_id = sid
        self.qs = self.ctx.tests.questions(sid)
        self.answers = {}
        self.idx = 0
        sess = self.ctx.tests.session(sid)
        self.who.setText(f"{sess['employee_name']} · {sess['department_name']}")
        self._build_palette()
        self.stack.setCurrentIndex(1)
        self.session_state.emit(True)
        self._render()
        if sess["time_limit_min"]:
            self.timer.start(1000)
            self._tick()
        else:
            self.timer_lbl.setText("")

    # ------------------------------------------------------------ вопросы
    def _build_quiz(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(40, 20, 40, 20)
        top = QHBoxLayout()
        self.who = label("", "Muted")
        self.counter = label("", "H2")
        self.answered_lbl = label("", "Muted")
        self.timer_lbl = label("", "Timer")
        top.addWidget(self.counter)
        top.addSpacing(16)
        top.addWidget(self.answered_lbl)
        top.addStretch(1)
        top.addWidget(self.who)
        top.addSpacing(16)
        top.addWidget(self.timer_lbl)
        lay.addLayout(top)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(8)
        lay.addWidget(self.progress)
        qcard, ql = card()
        self.qtype_lbl = label("", "Muted")
        self.qtext = label("", "QuestionText", wrap=True)
        self.qtext.setTextInteractionFlags(Qt.NoTextInteraction)
        ql.addWidget(self.qtype_lbl)
        ql.addWidget(self.qtext)
        ql.addSpacing(8)
        self.opts_box = QVBoxLayout()
        self.opts_box.setSpacing(8)
        ql.addLayout(self.opts_box)
        ql.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(qcard)
        lay.addWidget(scroll, 1)
        nav = QHBoxLayout()
        self.prev_btn = button(tr("emp_prev"), lambda: self._go(self.idx - 1))
        self.next_btn = button(tr("emp_next"), lambda: self._go(self.idx + 1), primary=True)
        self.finish_btn = button(tr("emp_finish"), self._confirm_finish)
        for b in (self.prev_btn, self.next_btn, self.finish_btn):
            b.setMinimumHeight(36)
        nav.addWidget(self.prev_btn)
        nav.addStretch(1)
        nav.addWidget(self.finish_btn)
        nav.addWidget(self.next_btn)
        lay.addLayout(nav)
        self.palette_wrap = QWidget()
        self.palette = QGridLayout(self.palette_wrap)
        self.palette.setSpacing(4)
        lay.addWidget(self.palette_wrap)
        self.stack.addWidget(w)
        self.group: QButtonGroup | None = None
        self.opt_widgets: list = []

    def _build_palette(self):
        while self.palette.count():
            it = self.palette.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.pal_btns = []
        cols = 15
        for i in range(len(self.qs)):
            b = QPushButton(str(i + 1))
            b.setFixedSize(38, 30)
            b.clicked.connect(lambda _=False, k=i: self._go(k))
            self.palette.addWidget(b, i // cols, i % cols)
            self.pal_btns.append(b)

    def _render(self):
        q = self.qs[self.idx]
        n = len(self.qs)
        self.counter.setText(tr("emp_q_of", i=self.idx + 1, n=n))
        done = sum(1 for v in self.answers.values() if v)
        self.answered_lbl.setText(tr("emp_answered", done=done, n=n))
        self.progress.setRange(0, n)
        self.progress.setValue(done)
        self.qtype_lbl.setText(tr(f"emp_hint_{q.qtype}"))
        self.qtext.setText(q.text)
        while self.opts_box.count():
            it = self.opts_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if self.group is not None:
            self.group.deleteLater()
        self.group = QButtonGroup(self)
        self.group.setExclusive(q.qtype != "multiple")
        chosen = set(self.answers.get(q.id, []))
        self.opt_widgets = []
        for k, o in enumerate(q.options):
            fr = QFrame()
            fr.setObjectName("Option")
            h = QHBoxLayout(fr)
            h.setContentsMargins(12, 10, 12, 10)
            btn = QCheckBox() if q.qtype == "multiple" else QRadioButton()
            btn.setChecked(k in chosen)
            txt = QLabel(o["text"])
            txt.setWordWrap(True)
            txt.setTextInteractionFlags(Qt.NoTextInteraction)
            h.addWidget(btn)
            h.addWidget(txt, 1)
            self.group.addButton(btn, k)
            fr.mousePressEvent = lambda ev, b=btn, multi=(q.qtype == "multiple"): (
                b.setChecked(not b.isChecked()) if multi else b.setChecked(True))
            btn.toggled.connect(self._changed)
            self.opts_box.addWidget(fr)
            self.opt_widgets.append(fr)
        self._style_options()
        self.prev_btn.setEnabled(self.idx > 0)
        self.next_btn.setEnabled(self.idx < n - 1)
        for i, b in enumerate(self.pal_btns):
            ans = bool(self.answers.get(self.qs[i].id))
            style = f"background:{theme.NAVY_LIGHT};color:white;" if ans else ""
            if i == self.idx:
                style += f"border:2px solid {theme.NAVY};"
            b.setStyleSheet(style)

    def _style_options(self):
        for k, fr in enumerate(self.opt_widgets):
            btn = self.group.button(k)
            fr.setProperty("selected", "true" if btn.isChecked() else "false")
            fr.style().unpolish(fr)
            fr.style().polish(fr)

    def _changed(self, _checked=None):
        q = self.qs[self.idx]
        sel = [k for k in range(len(q.options)) if self.group.button(k).isChecked()]
        try:
            self.ctx.tests.answer(self.session_id, q.id, sel)
        except TestBuildError as e:
            if e.key == "session_time_over":
                self._finish(expired=True)
                return
            error(self, e)
            return
        self.answers[q.id] = sel
        self._style_options()
        done = sum(1 for v in self.answers.values() if v)
        self.answered_lbl.setText(tr("emp_answered", done=done, n=len(self.qs)))
        self.progress.setValue(done)
        b = self.pal_btns[self.idx]
        b.setStyleSheet((f"background:{theme.NAVY_LIGHT};color:white;" if sel else "") + f"border:2px solid {theme.NAVY};")

    def _go(self, k: int):
        if 0 <= k < len(self.qs):
            self.idx = k
            self._render()

    def _tick(self):
        if self.session_id is None:
            self.timer.stop()
            return
        rem = self.ctx.tests.remaining_seconds(self.session_id)
        if rem is None:
            self.timer.stop()
            return
        m, s = divmod(rem, 60)
        self.timer_lbl.setText(tr("emp_time_left", t=f"{m:02d}:{s:02d}"))
        self.timer_lbl.setStyleSheet(f"color:{theme.BAD};" if rem <= 60 else "")
        if rem <= 0:
            self.timer.stop()
            self._finish(expired=True)

    def _confirm_finish(self):
        left = len(self.qs) - sum(1 for v in self.answers.values() if v)
        text = tr("emp_confirm_finish_left", n=left) if left else tr("emp_confirm_finish")
        if confirm(self, text):
            self._finish()

    def _finish(self, expired: bool = False):
        if self.session_id is None:
            return
        self.timer.stop()
        try:
            res = self.ctx.tests.finish(self.session_id, expired=expired)
        except Exception as e:
            error(self, e)
            return
        self._show_result(res, expired)

    # ------------------------------------------------------------ итог
    def _build_result(self):
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(40, 30, 40, 30)
        outer.addStretch(1)
        box, lay = card()
        box.setMaximumWidth(640)
        self.res_status = label("", "PageTitle")
        self.res_status.setAlignment(Qt.AlignCenter)
        self.res_score = label("", "StatValue")
        self.res_score.setAlignment(Qt.AlignCenter)
        self.res_details = label("", wrap=True)
        self.res_details.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.res_status)
        lay.addWidget(self.res_score)
        lay.addWidget(self.res_details)
        self.done_btn = button(tr("emp_done"), self._reset, primary=True)
        self.done_btn.setMinimumHeight(38)
        lay.addSpacing(8)
        lay.addWidget(self.done_btn)
        h = QHBoxLayout()
        h.addStretch(1)
        h.addWidget(box)
        h.addStretch(1)
        outer.addLayout(h)
        outer.addStretch(2)
        self.stack.addWidget(w)

    def _show_result(self, res: dict, expired: bool):
        passed = bool(res["passed"])
        self.res_status.setText(tr("status_passed") if passed else tr("status_failed"))
        self.res_status.setStyleSheet(f"color:{theme.OK if passed else theme.BAD};")
        self.res_score.setText(f"{res['percent']:.1f}%")
        lines = [tr("emp_res_line", correct=res["correct"], total=res["total"], wrong=res["wrong"]),
                 tr("emp_res_pass", p=res["pass_score"])]
        if expired:
            lines.insert(0, tr("emp_time_over"))
        lines.append(tr("emp_res_saved"))
        self.res_details.setText("\n".join(lines))
        self.stack.setCurrentIndex(2)

    def _reset(self):
        self.session_id = None
        self.qs, self.answers, self.idx = [], {}, 0
        self.fio.clear()
        self.position.clear()
        self.dept.setCurrentText("")
        self.stack.setCurrentIndex(0)
        self.session_state.emit(False)
        self.refresh()

    def in_session(self) -> bool:
        return self.session_id is not None and self.stack.currentIndex() == 1

    def retranslate(self):
        self.start_title.setText(tr("emp_title"))
        self.start_sub.setText(tr("emp_subtitle"))
        self.lbl_fio.setText(tr("emp_fio") + " *")
        self.lbl_dept.setText(tr("emp_dept") + " *")
        self.lbl_pos.setText(tr("emp_position"))
        self.lbl_prof.setText(tr("emp_profile"))
        self.start_btn.setText(tr("emp_start"))
        self.prev_btn.setText(tr("emp_prev"))
        self.next_btn.setText(tr("emp_next"))
        self.finish_btn.setText(tr("emp_finish"))
        self.done_btn.setText(tr("emp_done"))
        self._profile_info()
