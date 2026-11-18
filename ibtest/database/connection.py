"""Подключение к локальной базе SQLite."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ibtest.config import paths
from ibtest.database import migrations


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=15, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


class Database:
    """Единая точка доступа к БД. Потокобезопасна за счёт блокировки:
    фоновая генерация вопросов пишет в БД из рабочего потока."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else paths.db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = _connect(self.path)
        migrations.migrate(self.conn)

    # -- базовые операции -------------------------------------------------
    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, params)

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: tuple | dict = ()):
        row = self.one(sql, params)
        return None if row is None else row[0]

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self.conn.in_transaction:
                # Вложенная транзакция — точка сохранения.
                sp = f"sp_{id(object())}"
                self.conn.execute(f"SAVEPOINT {sp}")
                try:
                    yield self.conn
                    self.conn.execute(f"RELEASE {sp}")
                except Exception:
                    self.conn.execute(f"ROLLBACK TO {sp}")
                    self.conn.execute(f"RELEASE {sp}")
                    raise
                return
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def integrity_check(self) -> tuple[bool, str]:
        with self._lock:
            res = [r[0] for r in self.conn.execute("PRAGMA integrity_check").fetchall()]
            fk = self.conn.execute("PRAGMA foreign_key_check").fetchall()
        ok = res == ["ok"] and not fk
        msg = "; ".join(res) if res != ["ok"] else "ok"
        if fk:
            msg += f"; нарушений внешних ключей: {len(fk)}"
        return ok, msg

    def backup_to(self, target: Path) -> None:
        with self._lock:
            dst = sqlite3.connect(str(target))
            try:
                self.conn.backup(dst)
            finally:
                dst.close()

    def close(self) -> None:
        with self._lock:
            try:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
            self.conn.close()

    def reopen(self) -> None:
        with self._lock:
            self.conn = _connect(self.path)
            migrations.migrate(self.conn)
