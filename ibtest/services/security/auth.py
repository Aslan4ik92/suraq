"""Учётные записи администраторов, вход и журнал действий."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from ibtest.config.settings import Settings
from ibtest.database.connection import Database
from ibtest.models.common import now_iso
from ibtest.services.security import passwords


class AuthError(Exception):
    def __init__(self, key: str, **kw):
        super().__init__(key)
        self.key, self.kw = key, kw


@dataclass
class AdminSession:
    id: int
    username: str
    full_name: str
    role: str


class AuditLog:
    def __init__(self, db: Database):
        self.db = db
        self.current: AdminSession | None = None

    def log(self, action: str, entity: str = "", entity_id=None, details: dict | str | None = None) -> None:
        if isinstance(details, dict):
            details = json.dumps(details, ensure_ascii=False, default=str)
        self.db.execute(
            "INSERT INTO audit_logs(admin_id, username, action, entity, entity_id, details, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (self.current.id if self.current else None, self.current.username if self.current else None,
             action, entity, None if entity_id is None else str(entity_id), details, now_iso()))

    def list(self, limit: int = 500, search: str = "") -> list:
        if search:
            like = f"%{search}%"
            return self.db.query(
                "SELECT * FROM audit_logs WHERE action LIKE ? OR details LIKE ? OR username LIKE ? "
                "ORDER BY id DESC LIMIT ?", (like, like, like, limit))
        return self.db.query("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))


class AuthService:
    def __init__(self, db: Database, settings: Settings, audit: AuditLog):
        self.db, self.settings, self.audit = db, settings, audit

    def has_admins(self) -> bool:
        return bool(self.db.scalar("SELECT COUNT(*) FROM admin_users WHERE is_active = 1"))

    def create_admin(self, username: str, password: str, full_name: str = "", role: str = "admin") -> int:
        username = username.strip()
        if len(username) < 3:
            raise AuthError("login_too_short")
        probs = passwords.password_problems(password)
        if probs:
            raise AuthError(probs[0])
        if self.db.one("SELECT 1 FROM admin_users WHERE username = ?", (username,)):
            raise AuthError("login_exists")
        cur = self.db.execute(
            "INSERT INTO admin_users(username, full_name, password_hash, role, created_at) VALUES (?,?,?,?,?)",
            (username, full_name.strip(), passwords.hash_password(password), role, now_iso()))
        self.audit.log("admin_create", "admin_users", cur.lastrowid, {"username": username, "role": role})
        return cur.lastrowid

    def login(self, username: str, password: str) -> AdminSession:
        row = self.db.one("SELECT * FROM admin_users WHERE username = ?", (username.strip(),))
        if row is None or not row["is_active"]:
            self.audit.log("login_failed", "admin_users", None, {"username": username})
            raise AuthError("login_invalid")
        if row["locked_until"] and datetime.fromisoformat(row["locked_until"]) > datetime.now():
            raise AuthError("login_locked", until=row["locked_until"][11:16])
        if not passwords.verify_password(password, row["password_hash"]):
            attempts = row["failed_attempts"] + 1
            max_att = int(self.settings.get("login_max_attempts"))
            locked = None
            if attempts >= max_att:
                locked = (datetime.now() + timedelta(minutes=int(self.settings.get("login_lock_minutes")))
                          ).strftime("%Y-%m-%dT%H:%M:%S")
                attempts = 0
            self.db.execute("UPDATE admin_users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                            (attempts, locked, row["id"]))
            self.audit.log("login_failed", "admin_users", row["id"], {"username": username})
            if locked:
                raise AuthError("login_locked", until=locked[11:16])
            raise AuthError("login_invalid")
        new_hash = passwords.hash_password(password) if passwords.needs_rehash(row["password_hash"]) else row["password_hash"]
        self.db.execute("UPDATE admin_users SET failed_attempts = 0, locked_until = NULL, last_login_at = ?, "
                        "password_hash = ? WHERE id = ?", (now_iso(), new_hash, row["id"]))
        sess = AdminSession(row["id"], row["username"], row["full_name"] or "", row["role"])
        self.audit.current = sess
        self.audit.log("login", "admin_users", row["id"])
        return sess

    def logout(self) -> None:
        if self.audit.current:
            self.audit.log("logout", "admin_users", self.audit.current.id)
        self.audit.current = None

    def change_password(self, admin_id: int, old: str, new: str) -> None:
        row = self.db.one("SELECT * FROM admin_users WHERE id = ?", (admin_id,))
        if row is None or not passwords.verify_password(old, row["password_hash"]):
            raise AuthError("login_invalid")
        probs = passwords.password_problems(new)
        if probs:
            raise AuthError(probs[0])
        self.db.execute("UPDATE admin_users SET password_hash = ? WHERE id = ?",
                        (passwords.hash_password(new), admin_id))
        self.audit.log("password_change", "admin_users", admin_id)

    def reset_password(self, admin_id: int, new: str) -> None:
        probs = passwords.password_problems(new)
        if probs:
            raise AuthError(probs[0])
        self.db.execute("UPDATE admin_users SET password_hash = ?, failed_attempts = 0, locked_until = NULL "
                        "WHERE id = ?", (passwords.hash_password(new), admin_id))
        self.audit.log("password_reset", "admin_users", admin_id)

    def set_active(self, admin_id: int, active: bool) -> None:
        if not active:
            others = self.db.scalar("SELECT COUNT(*) FROM admin_users WHERE is_active = 1 AND id <> ? AND role='admin'",
                                    (admin_id,))
            if not others:
                raise AuthError("last_admin")
        self.db.execute("UPDATE admin_users SET is_active = ? WHERE id = ?", (int(active), admin_id))
        self.audit.log("admin_activate" if active else "admin_deactivate", "admin_users", admin_id)

    def list_admins(self) -> list:
        return self.db.query("SELECT id, username, full_name, role, is_active, last_login_at, created_at "
                             "FROM admin_users ORDER BY username")
