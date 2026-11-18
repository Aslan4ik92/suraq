"""Запуск графического приложения."""
from __future__ import annotations

import argparse
import logging
import sys
import traceback

from ibtest import __app_name__, __version__


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="IBTest")
    ap.add_argument("--kiosk", action="store_true", help="режим сотрудника (полноэкранный)")
    args, _ = ap.parse_known_args(argv)

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from ibtest.app_context import AppContext, setup_logging
    from ibtest.config import paths
    from ibtest.localization.i18n import set_language, tr
    from ibtest.ui.dialogs.login import FirstRunDialog
    from ibtest.ui.main_window import MainWindow
    from ibtest.ui.theme import QSS

    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("IBTest")
    app.setStyleSheet(QSS)
    app.setFont(QFont("Segoe UI", 10))
    icon = paths.assets_dir() / "ibtest.ico"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    try:
        setup_logging()
    except Exception:
        pass
    log = logging.getLogger("ibtest")

    def excepthook(exc_type, exc, tb):
        log.error("unhandled: %s", "".join(traceback.format_exception(exc_type, exc, tb)))
        QMessageBox.critical(None, __app_name__, f"{exc_type.__name__}: {exc}\n\n{tr('err_logged')}")

    sys.excepthook = excepthook

    try:
        ctx = AppContext()
    except Exception as e:
        log.exception("startup failed")
        QMessageBox.critical(None, __app_name__, f"Не удалось открыть базу данных / Дерекқорды ашу мүмкін болмады:\n{e}")
        return 1
    set_language(ctx.settings.get("ui_language"))
    ok, msg = ctx.db.integrity_check()
    if not ok:
        QMessageBox.critical(None, __app_name__, tr("db_corrupt", msg=msg))
    try:
        ctx.autodetect_model()
    except Exception:
        log.exception("model autodetect failed")
    try:
        n = ctx.tests.abort_stale()
        if n:
            log.info("closed %s stale sessions", n)
    except Exception:
        log.exception("abort_stale failed")

    if not ctx.auth.has_admins():
        dlg = FirstRunDialog(None, ctx)
        if not dlg.exec():
            return 0
    win = MainWindow(ctx, kiosk_only=args.kiosk)
    if args.kiosk:
        win.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        win.showFullScreen()
    else:
        win.showMaximized()
    code = app.exec()
    ctx.db.close()
    return code
