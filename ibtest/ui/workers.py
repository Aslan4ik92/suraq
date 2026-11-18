"""Фоновое выполнение длительных операций (разбор файлов, генерация, резервное копирование)."""
from __future__ import annotations

import logging
import threading
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from ibtest.localization.i18n import tr

log = logging.getLogger(__name__)


class Worker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(object)

    def __init__(self, fn: Callable[..., Any], *args, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.cancel = threading.Event()

    def run(self):
        try:
            res = self.fn(*self.args, progress=self._emit, cancel=self.cancel, **self.kwargs)
            self.finished.emit(res)
        except Exception as e:  # передаём в интерфейс, там показывается понятное сообщение
            log.error("worker failed: %s\n%s", e, traceback.format_exc())
            self.failed.emit(e)

    def _emit(self, done: int, total: int, stage: str = ""):
        self.progress.emit(int(done), int(total), stage)


class ProgressDialog(QDialog):
    """Модальное окно прогресса с отменой; выполняет функцию в отдельном потоке.

    Функция должна принимать именованные аргументы progress и cancel."""

    def __init__(self, parent: QWidget, title: str, fn: Callable, *args, cancellable: bool = True, **kwargs):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        self.lbl = QLabel(tr("progress_working"))
        self.lbl.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        lay.addWidget(self.lbl)
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = QPushButton(tr("cancel"))
        self.cancel_btn.setVisible(cancellable)
        self.cancel_btn.clicked.connect(self._cancel)
        row.addWidget(self.cancel_btn)
        lay.addLayout(row)
        self.result: Any = None
        self.error: Exception | None = None
        self._thread = QThread(self)
        self._worker = Worker(fn, *args, **kwargs)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_done)
        self._worker.failed.connect(self._on_fail)

    def exec(self) -> int:
        self._thread.start()
        return super().exec()

    def _on_progress(self, done: int, total: int, stage: str):
        if total > 0:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
        key = f"progress_{stage}" if stage else "progress_working"
        self.lbl.setText(tr(key, done=done, total=total))

    def _cancel(self):
        self._worker.cancel.set()
        self.cancel_btn.setEnabled(False)
        self.lbl.setText(tr("progress_cancelling"))

    def _finish(self):
        self._thread.quit()
        self._thread.wait(10000)

    def _on_done(self, res):
        self.result = res
        self._finish()
        self.accept()

    def _on_fail(self, e):
        self.error = e
        self._finish()
        self.reject()

    def closeEvent(self, ev):
        if self._thread.isRunning():
            self._cancel()
            ev.ignore()
            return
        super().closeEvent(ev)

    def reject(self):
        if self._thread.isRunning():
            self._cancel()
            return
        super().reject()


def run_with_progress(parent: QWidget, title: str, fn: Callable, *args, cancellable: bool = True, **kwargs):
    """Выполняет fn в фоне. Возвращает (результат, ошибка)."""
    dlg = ProgressDialog(parent, title, fn, *args, cancellable=cancellable, **kwargs)
    dlg.exec()
    return dlg.result, dlg.error
