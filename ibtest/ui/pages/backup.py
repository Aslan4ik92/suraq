"""Раздел «Резервное копирование»."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLineEdit,
                               QSpinBox)

from ibtest.localization.i18n import tr
from ibtest.ui.widgets.common import (PageBase, button, card, confirm, error, fill_table, fmt_dt, info, label,
                                      make_table, selected_key)
from ibtest.ui.workers import run_with_progress


def ask_password(parent, title: str, prompt: str) -> str | None:
    pwd, ok = QInputDialog.getText(parent, title, prompt, QLineEdit.Password)
    return pwd if ok else None


class BackupPage(PageBase):
    def __init__(self, ctx, navigate, restart_app):
        super().__init__(ctx, "nav_backup", "bk_subtitle")
        self.restart_app = restart_app
        top = QHBoxLayout()
        c, cl = card()
        cl.addWidget(label(tr("bk_settings"), "H2"))
        f = QFormLayout()
        self.dir = QLineEdit()
        self.dir.setReadOnly(True)
        d_row = QHBoxLayout()
        d_row.addWidget(self.dir, 1)
        d_row.addWidget(button(tr("browse"), self._choose_dir))
        self.auto = QCheckBox(tr("bk_auto"))
        self.interval = QSpinBox()
        self.interval.setRange(1, 24 * 30)
        self.interval.setSuffix(" " + tr("hours"))
        self.keep = QSpinBox()
        self.keep.setRange(1, 200)
        self.docs = QCheckBox(tr("bk_include_docs"))
        self.pwd_state = label("", "Muted")
        f.addRow(tr("bk_folder"), d_row)
        f.addRow("", self.auto)
        f.addRow(tr("bk_interval"), self.interval)
        f.addRow(tr("bk_keep"), self.keep)
        f.addRow("", self.docs)
        f.addRow(tr("bk_encryption"), self.pwd_state)
        cl.addLayout(f)
        r = QHBoxLayout()
        r.addWidget(button(tr("save"), self._save_settings, primary=True))
        r.addWidget(button(tr("bk_set_password"), self._set_password))
        r.addWidget(button(tr("bk_clear_password"), self._clear_password))
        r.addStretch(1)
        cl.addLayout(r)
        top.addWidget(c, 3)
        c2, cl2 = card()
        cl2.addWidget(label(tr("bk_actions"), "H2"))
        cl2.addWidget(button(tr("bk_create"), self._create, primary=True))
        cl2.addWidget(button(tr("bk_check_db"), self._check_db))
        cl2.addWidget(button(tr("bk_restore_file"), self._restore_file))
        self.db_state = label("", "Muted", wrap=True)
        cl2.addWidget(self.db_state)
        cl2.addStretch(1)
        top.addWidget(c2, 2)
        self.root.addLayout(top)
        self.table = make_table([tr("col_file"), tr("col_kind"), tr("col_created"), tr("col_size"), tr("bk_encrypted"),
                                 tr("bk_verified")], stretch_col=0)
        self.root.addWidget(self.table, 1)
        acts = QHBoxLayout()
        acts.addWidget(button(tr("bk_verify"), self._verify))
        acts.addWidget(button(tr("bk_restore"), self._restore_selected, danger=True))
        acts.addStretch(1)
        self.root.addLayout(acts)

    def refresh(self):
        s = self.ctx.settings
        self.dir.setText(str(self.ctx.backup.target_dir()))
        self.auto.setChecked(bool(s.get("backup_auto_enabled")))
        self.interval.setValue(int(s.get("backup_interval_hours")))
        self.keep.setValue(int(s.get("backup_keep")))
        self.docs.setChecked(bool(s.get("backup_include_documents")))
        self.pwd_state.setText(tr("bk_pwd_set") if self.ctx.backup.stored_password() else tr("bk_pwd_none"))
        rows = self.ctx.backup.list()
        fill_table(self.table, [[r["name"], tr(f"bk_kind_{r['kind']}"), fmt_dt(r["created_at"]),
                                 f"{r['size'] / 1024 / 1024:.1f} МБ", tr("yes") if r["encrypted"] else tr("no"),
                                 "" if r["integrity_ok"] is None else (tr("yes") if r["integrity_ok"] else tr("no"))]
                                for r in rows], keys=[r["path"] for r in rows])
        last = s.get("backup_last_auto_at")
        self.db_state.setText(tr("bk_last_auto", t=fmt_dt(last) if last else "—"))

    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("bk_folder"), self.dir.text())
        if d:
            self.dir.setText(d)

    def _save_settings(self):
        self.ctx.settings.set_many({"backup_dir": self.dir.text(), "backup_auto_enabled": self.auto.isChecked(),
                                    "backup_interval_hours": self.interval.value(), "backup_keep": self.keep.value(),
                                    "backup_include_documents": self.docs.isChecked()})
        self.ctx.audit.log("settings_backup", "application_settings")
        info(self, tr("saved"))
        self.refresh()

    def _set_password(self):
        p1 = ask_password(self, tr("bk_set_password"), tr("bk_pwd_enter"))
        if not p1:
            return
        p2 = ask_password(self, tr("bk_set_password"), tr("bk_pwd_repeat"))
        if p1 != p2:
            error(self, tr("bk_pwd_mismatch"))
            return
        if len(p1) < 8:
            error(self, tr("pwd_too_short"))
            return
        self.ctx.backup.set_stored_password(p1)
        info(self, tr("bk_pwd_saved"))
        self.refresh()

    def _clear_password(self):
        if confirm(self, tr("bk_pwd_clear_confirm")):
            self.ctx.backup.set_stored_password(None)
            self.refresh()

    def _create(self):
        pwd = self.ctx.backup.stored_password()

        def job(progress, cancel):
            return self.ctx.backup.create("manual", password=pwd)

        res, err = run_with_progress(self, tr("bk_create"), job, cancellable=False)
        if err:
            error(self, err)
            return
        info(self, tr("bk_created", path=str(res)))
        self.refresh()

    def _check_db(self):
        ok, msg = self.ctx.db.integrity_check()
        (info if ok else error)(self, tr("bk_db_ok") if ok else tr("bk_db_bad", msg=msg))

    def _password_for(self, path: Path) -> str | None | bool:
        from ibtest.services.security import crypto
        with open(path, "rb") as f:
            enc = crypto.is_encrypted(f.read(16))
        if not enc:
            return None
        stored = self.ctx.backup.stored_password()
        if stored:
            chk = self.ctx.backup.verify(path, stored)
            if chk.ok:
                return stored
        p = ask_password(self, tr("bk_password"), tr("bk_pwd_for_file", f=path.name))
        return p if p else False

    def _verify(self):
        path = selected_key(self.table)
        if not path:
            info(self, tr("select_row"))
            return
        pwd = self._password_for(Path(path))
        if pwd is False:
            return
        res, err = run_with_progress(self, tr("bk_verify"), lambda progress, cancel: self.ctx.backup.verify(Path(path), pwd),
                                     cancellable=False)
        if err:
            error(self, err)
            return
        if res.ok:
            info(self, tr("bk_verify_ok", t=fmt_dt(res.created_at), v=res.app_version, tests=res.tests, docs=res.documents))
        else:
            error(self, tr("bk_verify_bad", msg=tr(res.message)))

    def _restore_file(self):
        fn, _ = QFileDialog.getOpenFileName(self, tr("bk_restore_file"), str(self.ctx.backup.target_dir()),
                                            "IBTest backup (*.ibtbak)")
        if fn:
            self._restore(Path(fn))

    def _restore_selected(self):
        path = selected_key(self.table)
        if not path:
            info(self, tr("select_row"))
            return
        self._restore(Path(path))

    def _restore(self, path: Path):
        pwd = self._password_for(path)
        if pwd is False:
            return
        chk = self.ctx.backup.verify(path, pwd)
        if not chk.ok:
            error(self, tr("bk_verify_bad", msg=tr(chk.message)))
            return
        cur_tests = self.ctx.db.scalar("SELECT COUNT(*) FROM test_results")
        text = tr("bk_restore_confirm", t=fmt_dt(chk.created_at), tests=chk.tests, docs=chk.documents, cur=cur_tests)
        if not confirm(self, text, danger=True):
            return
        word, ok = QInputDialog.getText(self, tr("bk_restore"), tr("bk_restore_type_word"))
        if not ok or word.strip().upper() not in ("ВОССТАНОВИТЬ", "ҚАЛПЫНА", "RESTORE"):
            return
        safety_pwd = self.ctx.backup.stored_password()

        def job(progress, cancel):
            return self.ctx.backup.restore(path, pwd, safety_password=safety_pwd)

        res, err = run_with_progress(self, tr("bk_restore"), job, cancellable=False)
        if err:
            error(self, err)
            return
        info(self, tr("bk_restored", safety=res.name))
        self.restart_app()
