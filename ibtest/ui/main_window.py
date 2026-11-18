"""Главное окно: режим сотрудника и административная панель."""
from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QMainWindow, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from ibtest import __app_name__, __version__
from ibtest.localization.i18n import set_language, tr
from ibtest.ui.dialogs.login import LoginDialog
from ibtest.ui.pages.analytics import AnalyticsPage
from ibtest.ui.pages.backup import BackupPage
from ibtest.ui.pages.control import ControlPage
from ibtest.ui.pages.documents import DocumentsPage
from ibtest.ui.pages.employee_test import EmployeeTestPage
from ibtest.ui.pages.employees import EmployeesPage
from ibtest.ui.pages.home import HomePage
from ibtest.ui.pages.questions import QuestionsPage
from ibtest.ui.pages.results import ResultsPage
from ibtest.ui.pages.review import ReviewPage
from ibtest.ui.pages.revisions import RevisionsPage
from ibtest.ui.pages.settings import SettingsPage
from ibtest.ui.pages.testing_admin import TestingAdminPage
from ibtest.ui.widgets.common import button, confirm, label

log = logging.getLogger(__name__)

NAV = [("home", "nav_home"), ("testing", "nav_testing"), ("documents", "nav_documents"),
       ("revisions", "nav_revisions"), ("questions", "nav_questions"), ("review", "nav_review"),
       ("results", "nav_results"), ("control", "nav_control"), ("employees", "nav_employees"),
       ("analytics", "nav_analytics"), ("backup", "nav_backup"), ("settings", "nav_settings")]


class ActivityFilter(QObject):
    def __init__(self):
        super().__init__()
        self.last = time.monotonic()

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.MouseButtonPress, QEvent.KeyPress, QEvent.Wheel, QEvent.MouseMove):
            self.last = time.monotonic()
        return False


class AdminShell(QWidget):
    def __init__(self, ctx, main: "MainWindow"):
        super().__init__()
        self.ctx, self.main = ctx, main
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(250)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 10)
        sl.setSpacing(0)
        sl.addWidget(label(__app_name__, "AppTitle"))
        sl.addWidget(label(tr("app_subtitle") + f" · v{__version__}", "AppSubtitle"))
        self.group = QButtonGroup(self)
        self.btns: dict[str, QPushButton] = {}
        for i, (key, tkey) in enumerate(NAV, start=1):
            b = QPushButton(f"{i:>2}.  {tr(tkey)}")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.navigate(k))
            self.group.addButton(b)
            sl.addWidget(b)
            self.btns[key] = b
        sl.addStretch(1)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        top = QWidget()
        top.setObjectName("TopBar")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(20, 8, 20, 8)
        tl.addStretch(1)
        user = ctx.audit.current
        tl.addWidget(label(tr("top_admin", name=(user.full_name or user.username) if user else ""), "Muted"))
        self.lang_btn = button("Қазақша" if ctx.settings.get("ui_language") == "ru" else "Русский", self._toggle_lang)
        tl.addWidget(self.lang_btn)
        tl.addWidget(button(tr("top_logout"), self.main.logout))
        rl.addWidget(top)
        self.stack = QStackedWidget()
        rl.addWidget(self.stack, 1)
        lay.addWidget(side)
        lay.addWidget(right, 1)
        nav = self.navigate
        self.pages = {
            "home": HomePage(ctx, nav),
            "testing": TestingAdminPage(ctx, nav, self.main.start_employee_mode),
            "documents": DocumentsPage(ctx, nav),
            "revisions": RevisionsPage(ctx, nav),
            "questions": QuestionsPage(ctx, nav),
            "review": ReviewPage(ctx, nav),
            "results": ResultsPage(ctx, nav),
            "control": ControlPage(ctx, nav),
            "employees": EmployeesPage(ctx, nav),
            "analytics": AnalyticsPage(ctx, nav),
            "backup": BackupPage(ctx, nav, self.main.rebuild),
            "settings": SettingsPage(ctx, nav, self.main.rebuild),
        }
        for p in self.pages.values():
            self.stack.addWidget(p)
        self.navigate("home")

    def navigate(self, key: str, arg=None):
        page = self.pages[key]
        self.btns[key].setChecked(True)
        self.stack.setCurrentWidget(page)
        try:
            if key == "revisions" and arg is not None:
                page.select_document(arg)
            else:
                page.refresh()
        except Exception as e:  # ошибка обновления страницы не должна закрывать программу
            log.exception("page refresh failed")
            from ibtest.ui.widgets.common import error
            error(self, e)

    def _toggle_lang(self):
        new = "kk" if self.ctx.settings.get("ui_language") == "ru" else "ru"
        self.ctx.settings.set("ui_language", new)
        self.main.rebuild()


class MainWindow(QMainWindow):
    def __init__(self, ctx, kiosk_only: bool = False):
        super().__init__()
        self.ctx = ctx
        self.kiosk_only = kiosk_only
        self.setWindowTitle(f"{__app_name__} {__version__}")
        self.resize(1360, 860)
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.employee: EmployeeTestPage | None = None
        self.admin: AdminShell | None = None
        self._build_employee()
        self.activity = ActivityFilter()
        QApplication.instance().installEventFilter(self.activity)
        self.idle_timer = QTimer(self)
        self.idle_timer.timeout.connect(self._check_idle)
        self.idle_timer.start(30_000)
        self.backup_timer = QTimer(self)
        self.backup_timer.timeout.connect(self._auto_backup)
        self.backup_timer.start(30 * 60_000)
        QTimer.singleShot(5_000, self._auto_backup)
        self.show_employee()

    # -- режимы ---------------------------------------------------------------------
    def _build_employee(self):
        if self.employee is not None:
            self.stack.removeWidget(self.employee)
            self.employee.deleteLater()
        self.employee = EmployeeTestPage(self.ctx, kiosk=True)
        self.employee.admin_requested.connect(self.login)
        self.stack.addWidget(self.employee)

    def show_employee(self):
        self.stack.setCurrentWidget(self.employee)
        self.employee.refresh()

    def start_employee_mode(self):
        self.logout()

    def login(self):
        if self.employee and self.employee.in_session():
            return
        dlg = LoginDialog(self, self.ctx)
        if dlg.exec() and dlg.session:
            if dlg.session.role not in ("admin", "auditor"):
                return
            self._build_admin()
            self.stack.setCurrentWidget(self.admin)
            self.activity.last = time.monotonic()

    def _build_admin(self):
        if self.admin is not None:
            self.stack.removeWidget(self.admin)
            self.admin.deleteLater()
        self.admin = AdminShell(self.ctx, self)
        self.stack.addWidget(self.admin)

    def logout(self):
        self.ctx.auth.logout()
        if self.admin is not None:
            self.stack.removeWidget(self.admin)
            self.admin.deleteLater()
            self.admin = None
        self.show_employee()

    def rebuild(self):
        """Перестроение интерфейса (смена языка, восстановление из копии)."""
        set_language(self.ctx.settings.get("ui_language"))
        was_admin = self.admin is not None and self.ctx.audit.current is not None
        self._build_employee()
        if was_admin:
            self._build_admin()
            self.stack.setCurrentWidget(self.admin)
        else:
            self.show_employee()

    # -- фоновые задачи ---------------------------------------------------------------
    def _check_idle(self):
        if self.admin is None or self.stack.currentWidget() is not self.admin:
            return
        limit = int(self.ctx.settings.get("admin_idle_lock_min")) * 60
        if time.monotonic() - self.activity.last > limit and not QApplication.activeModalWidget():
            self.ctx.audit.log("idle_logout", "admin_users", self.ctx.audit.current.id if self.ctx.audit.current else None)
            self.logout()

    def _auto_backup(self):
        if self.employee and self.employee.in_session():
            return  # не нагружать диск во время тестирования

        def work():
            try:
                p = self.ctx.backup.run_auto_if_due()
                if p:
                    log.info("auto backup created: %s", p)
            except Exception:
                log.exception("auto backup failed")

        threading.Thread(target=work, daemon=True).start()

    def closeEvent(self, ev):
        if self.employee and self.employee.in_session():
            if not confirm(self, tr("close_during_test")):
                ev.ignore()
                return
        self.ctx.auth.logout()
        super().closeEvent(ev)
