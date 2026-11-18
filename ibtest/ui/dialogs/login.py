"""Вход администратора и первичная настройка."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QVBoxLayout

from ibtest.localization.i18n import tr
from ibtest.services.security.auth import AuthError
from ibtest.ui.widgets.common import error, label, warn


class LoginDialog(QDialog):
    def __init__(self, parent, ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.session = None
        self.setWindowTitle(tr("login_title"))
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.addWidget(label(tr("login_title"), "H2"))
        f = QFormLayout()
        self.user = QLineEdit()
        self.pwd = QLineEdit()
        self.pwd.setEchoMode(QLineEdit.Password)
        f.addRow(tr("adm_login"), self.user)
        f.addRow(tr("adm_password"), self.pwd)
        lay.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("login_enter"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("cancel"))
        bb.accepted.connect(self._login)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.pwd.returnPressed.connect(self._login)

    def _login(self):
        try:
            self.session = self.ctx.auth.login(self.user.text(), self.pwd.text())
        except AuthError as e:
            self.pwd.clear()
            error(self, e)
            return
        self.accept()


class FirstRunDialog(QDialog):
    """Создание первой учётной записи администратора."""

    def __init__(self, parent, ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(tr("first_title"))
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.addWidget(label(tr("first_title"), "H2"))
        lay.addWidget(label(tr("first_text"), "Muted", wrap=True))
        f = QFormLayout()
        self.user = QLineEdit("admin")
        self.name = QLineEdit()
        self.p1 = QLineEdit()
        self.p2 = QLineEdit()
        for p in (self.p1, self.p2):
            p.setEchoMode(QLineEdit.Password)
        self.org = QLineEdit()
        f.addRow(tr("adm_login") + " *", self.user)
        f.addRow(tr("adm_name"), self.name)
        f.addRow(tr("adm_password") + " *", self.p1)
        f.addRow(tr("bk_pwd_repeat") + " *", self.p2)
        f.addRow(tr("set_org"), self.org)
        lay.addLayout(f)
        lay.addWidget(label(tr("first_pwd_rules"), "Muted", wrap=True))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("first_create"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("cancel"))
        bb.accepted.connect(self._create)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _create(self):
        if self.p1.text() != self.p2.text():
            warn(self, tr("bk_pwd_mismatch"))
            return
        try:
            self.ctx.auth.create_admin(self.user.text(), self.p1.text(), self.name.text())
        except AuthError as e:
            error(self, e)
            return
        if self.org.text().strip():
            self.ctx.settings.set("organization_name", self.org.text().strip())
        self.accept()
