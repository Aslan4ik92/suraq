"""Справочник подразделений и сотрудников."""
from __future__ import annotations

import sqlite3

from ibtest.database.connection import Database
from ibtest.models.common import clean_person_name, new_uid, normalize_name, now_iso
from ibtest.services.security.auth import AuditLog


class EmployeeError(Exception):
    pass


class EmployeeService:
    def __init__(self, db: Database, audit: AuditLog):
        self.db, self.audit = db, audit

    # -- подразделения ------------------------------------------------------
    def departments(self, active_only: bool = False) -> list:
        sql = "SELECT d.*, (SELECT COUNT(*) FROM employees e WHERE e.department_id = d.id AND e.is_active=1) AS emp_count " \
              "FROM departments d"
        if active_only:
            sql += " WHERE d.is_active = 1"
        return self.db.query(sql + " ORDER BY d.name_norm")

    def add_department(self, name: str) -> int:
        name = " ".join(name.split())
        if not name:
            raise EmployeeError("dept_empty")
        try:
            cur = self.db.execute("INSERT INTO departments(name, name_norm, created_at) VALUES (?,?,?)",
                                  (name, normalize_name(name), now_iso()))
        except sqlite3.IntegrityError as exc:
            raise EmployeeError("dept_exists") from exc
        self.audit.log("department_add", "departments", cur.lastrowid, {"name": name})
        return cur.lastrowid

    def get_or_create_department(self, name: str) -> int:
        name = " ".join(name.split())
        row = self.db.one("SELECT id, is_active FROM departments WHERE name_norm = ?", (normalize_name(name),))
        if row:
            if not row["is_active"]:
                self.db.execute("UPDATE departments SET is_active = 1 WHERE id = ?", (row["id"],))
            return row["id"]
        cur = self.db.execute("INSERT INTO departments(name, name_norm, created_at) VALUES (?,?,?)",
                              (name, normalize_name(name), now_iso()))
        return cur.lastrowid

    def rename_department(self, dept_id: int, name: str) -> None:
        name = " ".join(name.split())
        if not name:
            raise EmployeeError("dept_empty")
        try:
            self.db.execute("UPDATE departments SET name = ?, name_norm = ? WHERE id = ?",
                            (name, normalize_name(name), dept_id))
        except sqlite3.IntegrityError as exc:
            raise EmployeeError("dept_exists") from exc
        self.audit.log("department_rename", "departments", dept_id, {"name": name})

    def set_department_active(self, dept_id: int, active: bool) -> None:
        self.db.execute("UPDATE departments SET is_active = ? WHERE id = ?", (int(active), dept_id))
        self.audit.log("department_activate" if active else "department_archive", "departments", dept_id)

    def delete_department(self, dept_id: int) -> None:
        if self.db.scalar("SELECT COUNT(*) FROM employees WHERE department_id = ?", (dept_id,)):
            raise EmployeeError("dept_has_employees")
        self.db.execute("DELETE FROM departments WHERE id = ?", (dept_id,))
        self.audit.log("department_delete", "departments", dept_id)

    # -- сотрудники ---------------------------------------------------------
    def find_or_create(self, full_name: str, department_name: str, position: str = "") -> int:
        """Находит сотрудника по нормализованному ФИО и подразделению или создаёт."""
        full_name = clean_person_name(full_name)
        if len(full_name.split()) < 2:
            raise EmployeeError("fio_invalid")
        if not department_name.strip():
            raise EmployeeError("dept_empty")
        with self.db.transaction():
            dept_id = self.get_or_create_department(department_name)
            norm = normalize_name(full_name)
            row = self.db.one("SELECT id, position FROM employees WHERE full_name_norm = ? AND department_id = ?",
                              (norm, dept_id))
            if row:
                if position and position != (row["position"] or ""):
                    self.db.execute("UPDATE employees SET position = ? WHERE id = ?", (position.strip(), row["id"]))
                self.db.execute("UPDATE employees SET is_active = 1 WHERE id = ?", (row["id"],))
                return row["id"]
            cur = self.db.execute(
                "INSERT INTO employees(uid, full_name, full_name_norm, department_id, position, created_at) "
                "VALUES (?,?,?,?,?,?)", (new_uid("e_"), full_name, norm, dept_id, position.strip() or None, now_iso()))
            return cur.lastrowid

    def add_employee(self, full_name: str, department_id: int, position: str = "") -> int:
        full_name = clean_person_name(full_name)
        if len(full_name.split()) < 2:
            raise EmployeeError("fio_invalid")
        try:
            cur = self.db.execute(
                "INSERT INTO employees(uid, full_name, full_name_norm, department_id, position, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (new_uid("e_"), full_name, normalize_name(full_name), department_id, position.strip() or None, now_iso()))
        except sqlite3.IntegrityError as exc:
            raise EmployeeError("employee_exists") from exc
        self.audit.log("employee_add", "employees", cur.lastrowid, {"name": full_name})
        return cur.lastrowid

    def update_employee(self, emp_id: int, full_name: str, department_id: int, position: str) -> None:
        full_name = clean_person_name(full_name)
        if len(full_name.split()) < 2:
            raise EmployeeError("fio_invalid")
        try:
            self.db.execute("UPDATE employees SET full_name=?, full_name_norm=?, department_id=?, position=? WHERE id=?",
                            (full_name, normalize_name(full_name), department_id, position.strip() or None, emp_id))
        except sqlite3.IntegrityError as exc:
            raise EmployeeError("employee_exists") from exc
        self.audit.log("employee_update", "employees", emp_id, {"name": full_name})

    def set_employee_active(self, emp_id: int, active: bool) -> None:
        self.db.execute("UPDATE employees SET is_active = ? WHERE id = ?", (int(active), emp_id))
        self.audit.log("employee_activate" if active else "employee_archive", "employees", emp_id)

    def import_rows(self, rows: list[tuple[str, str, str]]) -> tuple[int, list[str]]:
        """Импорт из таблицы (ФИО, подразделение, должность). Возвращает (добавлено, ошибки)."""
        added, errors = 0, []
        before = self.db.scalar("SELECT COUNT(*) FROM employees")
        for i, (fio, dept, pos) in enumerate(rows, start=1):
            try:
                self.find_or_create(fio or "", dept or "", pos or "")
            except EmployeeError as e:
                errors.append(f"{i}: {fio} — {e}")
        added = self.db.scalar("SELECT COUNT(*) FROM employees") - before
        self.audit.log("employee_import", "employees", None, {"added": added, "errors": len(errors)})
        return added, errors

    def list(self, search: str = "", department_id: int | None = None, active_only: bool = True) -> list:
        sql = ("SELECT e.*, d.name AS department_name, "
               "(SELECT COUNT(*) FROM test_sessions s WHERE s.employee_id = e.id AND s.status <> 'in_progress') AS attempts "
               "FROM employees e JOIN departments d ON d.id = e.department_id WHERE 1=1")
        params: list = []
        if active_only:
            sql += " AND e.is_active = 1"
        if department_id:
            sql += " AND e.department_id = ?"
            params.append(department_id)
        if search:
            sql += " AND e.full_name_norm LIKE ?"
            params.append(f"%{normalize_name(search)}%")
        return self.db.query(sql + " ORDER BY e.full_name_norm", tuple(params))

    def get(self, emp_id: int):
        return self.db.one("SELECT e.*, d.name AS department_name FROM employees e "
                           "JOIN departments d ON d.id = e.department_id WHERE e.id = ?", (emp_id,))
