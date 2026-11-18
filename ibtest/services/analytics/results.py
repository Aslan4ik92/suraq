"""Журнал результатов, карточка сотрудника, контроль прохождения и аналитика."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ibtest.database.connection import Database


@dataclass
class ResultFilter:
    search: str = ""
    department_id: int | None = None
    document_id: int | None = None
    version_id: int | None = None
    status: str | None = None          # 'passed' | 'failed'
    date_from: str | None = None       # YYYY-MM-DD
    date_to: str | None = None
    employee_id: int | None = None
    sort: str = "date_desc"            # date_desc | date_asc | score_desc | score_asc


_SORTS = {"date_desc": "s.started_at DESC", "date_asc": "s.started_at ASC",
          "score_desc": "r.percent DESC, s.started_at DESC", "score_asc": "r.percent ASC, s.started_at DESC"}


def period_range(kind: str, ref: date | None = None) -> tuple[str, str]:
    ref = ref or date.today()
    if kind == "day":
        a = b = ref
    elif kind == "week":
        a = ref - timedelta(days=ref.weekday())
        b = a + timedelta(days=6)
    elif kind == "month":
        a = ref.replace(day=1)
        b = (a.replace(year=a.year + 1, month=1) if a.month == 12 else a.replace(month=a.month + 1)) - timedelta(days=1)
    else:
        raise ValueError(kind)
    return a.isoformat(), b.isoformat()


class ResultsService:
    def __init__(self, db: Database):
        self.db = db

    def _where(self, f: ResultFilter) -> tuple[str, list]:
        w, p = ["s.status IN ('finished','expired')"], []
        if f.search:
            from ibtest.models.common import normalize_name
            w.append("e.full_name_norm LIKE ?")
            p.append(f"%{normalize_name(f.search)}%")
        if f.department_id:
            w.append("e.department_id = ?")
            p.append(f.department_id)
        if f.employee_id:
            w.append("s.employee_id = ?")
            p.append(f.employee_id)
        if f.document_id:
            w.append("EXISTS (SELECT 1 FROM test_questions tq WHERE tq.session_id = s.id AND tq.document_id = ?)")
            p.append(f.document_id)
        if f.version_id:
            w.append("EXISTS (SELECT 1 FROM test_questions tq WHERE tq.session_id = s.id AND tq.version_id = ?)")
            p.append(f.version_id)
        if f.status == "passed":
            w.append("r.passed = 1")
        elif f.status == "failed":
            w.append("r.passed = 0")
        if f.date_from:
            w.append("date(s.started_at) >= date(?)")
            p.append(f.date_from)
        if f.date_to:
            w.append("date(s.started_at) <= date(?)")
            p.append(f.date_to)
        return " AND ".join(w), p

    def list(self, f: ResultFilter, limit: int = 20000) -> list[dict]:
        where, p = self._where(f)
        rows = self.db.query(
            "SELECT s.id AS session_id, s.uid, s.employee_id, s.employee_name, s.department_name, s.position, "
            "s.started_at, s.finished_at, s.duration_sec, s.status AS session_status, s.profile_name, s.pass_score, "
            "r.total, r.correct, r.wrong, r.unanswered, r.percent, r.passed, "
            "(SELECT group_concat(x, '; ') FROM (SELECT DISTINCT tq.document_title || ' (ред. ' || tq.version_no || ')' AS x "
            "  FROM test_questions tq WHERE tq.session_id = s.id)) AS documents "
            f"FROM test_sessions s JOIN test_results r ON r.session_id = s.id JOIN employees e ON e.id = s.employee_id "
            f"WHERE {where} ORDER BY {_SORTS.get(f.sort, _SORTS['date_desc'])} LIMIT ?", tuple(p + [limit]))
        return [dict(r) for r in rows]

    def summary(self, f: ResultFilter) -> dict:
        where, p = self._where(f)
        r = self.db.one(
            "SELECT COUNT(*) AS tests, COUNT(DISTINCT s.employee_id) AS employees, "
            "SUM(r.passed) AS passed, SUM(1 - r.passed) AS failed, AVG(r.percent) AS avg_percent "
            f"FROM test_sessions s JOIN test_results r ON r.session_id = s.id JOIN employees e ON e.id = s.employee_id "
            f"WHERE {where}", tuple(p))
        tests = r["tests"] or 0
        return {"tests": tests, "employees": r["employees"] or 0, "passed": r["passed"] or 0,
                "failed": r["failed"] or 0, "avg_percent": round(r["avg_percent"] or 0, 1),
                "pass_rate": round((r["passed"] or 0) * 100.0 / tests, 1) if tests else 0.0}

    def by_department(self, f: ResultFilter) -> list[dict]:
        where, p = self._where(f)
        return [dict(r) for r in self.db.query(
            "SELECT s.department_name AS name, COUNT(*) AS tests, COUNT(DISTINCT s.employee_id) AS employees, "
            "SUM(r.passed) AS passed, ROUND(AVG(r.percent),1) AS avg_percent "
            f"FROM test_sessions s JOIN test_results r ON r.session_id = s.id JOIN employees e ON e.id = s.employee_id "
            f"WHERE {where} GROUP BY s.department_name ORDER BY s.department_name", tuple(p))]

    def by_document(self, f: ResultFilter) -> list[dict]:
        where, p = self._where(f)
        return [dict(r) for r in self.db.query(
            "SELECT tq.document_title AS name, tq.version_no, COUNT(DISTINCT s.id) AS tests, "
            "ROUND(100.0 * SUM(CASE WHEN a.is_correct = 1 THEN 1 ELSE 0 END) / COUNT(tq.id), 1) AS correct_rate, "
            "COUNT(DISTINCT CASE WHEN r.passed = 1 THEN s.id END) AS passed "
            "FROM test_sessions s JOIN test_results r ON r.session_id = s.id JOIN employees e ON e.id = s.employee_id "
            "JOIN test_questions tq ON tq.session_id = s.id LEFT JOIN employee_answers a ON a.test_question_id = tq.id "
            f"WHERE {where} GROUP BY tq.document_title, tq.version_no ORDER BY tq.document_title, tq.version_no",
            tuple(p))]

    def by_month(self, f: ResultFilter) -> list[dict]:
        where, p = self._where(f)
        return [dict(r) for r in self.db.query(
            "SELECT strftime('%Y-%m', s.started_at) AS month, COUNT(*) AS tests, SUM(r.passed) AS passed, "
            "ROUND(AVG(r.percent),1) AS avg_percent "
            f"FROM test_sessions s JOIN test_results r ON r.session_id = s.id JOIN employees e ON e.id = s.employee_id "
            f"WHERE {where} GROUP BY month ORDER BY month", tuple(p))]

    def hardest_questions(self, f: ResultFilter, limit: int = 15) -> list[dict]:
        where, p = self._where(f)
        return [dict(r) for r in self.db.query(
            "SELECT tq.question_uid, MAX(tq.text) AS text, MAX(tq.document_title) AS document, COUNT(*) AS shown, "
            "ROUND(100.0 * SUM(CASE WHEN a.is_correct = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS correct_rate "
            "FROM test_sessions s JOIN test_results r ON r.session_id = s.id JOIN employees e ON e.id = s.employee_id "
            "JOIN test_questions tq ON tq.session_id = s.id LEFT JOIN employee_answers a ON a.test_question_id = tq.id "
            f"WHERE {where} GROUP BY tq.question_uid HAVING shown >= 3 ORDER BY correct_rate ASC LIMIT ?",
            tuple(p + [limit]))]

    # -- карточка сотрудника ----------------------------------------------------------
    def employee_card(self, employee_id: int) -> dict:
        emp = self.db.one("SELECT e.*, d.name AS department_name FROM employees e JOIN departments d "
                          "ON d.id = e.department_id WHERE e.id = ?", (employee_id,))
        attempts = self.list(ResultFilter(employee_id=employee_id, sort="date_asc"))
        docs = [dict(r) for r in self.db.query(
            "SELECT tq.document_id, tq.document_title, tq.version_no, COUNT(DISTINCT s.id) AS attempts, "
            "MAX(CASE WHEN r.passed = 1 THEN s.finished_at END) AS last_passed "
            "FROM test_sessions s JOIN test_results r ON r.session_id = s.id JOIN test_questions tq ON tq.session_id = s.id "
            "WHERE s.employee_id = ? GROUP BY tq.document_id, tq.document_title, tq.version_no "
            "ORDER BY tq.document_title, tq.version_no", (employee_id,))]
        return {"employee": dict(emp) if emp else None, "attempts": attempts, "documents": docs}

    # -- контроль прохождения --------------------------------------------------------
    def control(self, document_id: int, department_id: int | None = None) -> list[dict]:
        """Статус каждого активного сотрудника по документу:
        passed / failed / not_tested / retest (сдавал прежнюю редакцию, требования изменились)."""
        doc = self.db.one("SELECT * FROM documents WHERE id = ?", (document_id,))
        if doc is None:
            return []
        sql = ("SELECT e.id, e.full_name, e.position, d.name AS department_name FROM employees e "
               "JOIN departments d ON d.id = e.department_id WHERE e.is_active = 1")
        p: list = []
        if department_id:
            sql += " AND e.department_id = ?"
            p.append(department_id)
        emps = self.db.query(sql + " ORDER BY d.name, e.full_name", tuple(p))
        by_emp: dict[int, list] = {}
        for r in self.db.query(
                "SELECT s.employee_id, s.id, s.finished_at, r.percent, r.passed, "
                "(SELECT MAX(tq.version_id) FROM test_questions tq WHERE tq.session_id = s.id AND tq.document_id = ?) AS vid, "
                "(SELECT MAX(tq.version_no) FROM test_questions tq WHERE tq.session_id = s.id AND tq.document_id = ?) AS vno "
                "FROM test_sessions s JOIN test_results r ON r.session_id = s.id "
                "WHERE s.status IN ('finished','expired') AND EXISTS (SELECT 1 FROM test_questions tq "
                "WHERE tq.session_id = s.id AND tq.document_id = ?) ORDER BY s.finished_at",
                (document_id, document_id, document_id)):
            by_emp.setdefault(r["employee_id"], []).append(r)
        last = {}
        for emp_id, atts in by_emp.items():
            # Приоритет: последняя успешная попытка по действующей редакции, иначе последняя попытка.
            ok_active = [a for a in atts if a["passed"] and a["vid"] == doc["active_version_id"]]
            last[emp_id] = ok_active[-1] if ok_active else atts[-1]
        changed_versions = {r["old_version_id"] for r in self.db.query(
            "SELECT DISTINCT c.old_version_id FROM document_changes c JOIN document_versions v ON v.id = c.new_version_id "
            "WHERE v.document_id = ? AND v.status IN ('active','superseded') "
            "AND c.change_type IN ('added','modified','removed','manual')", (document_id,))}
        out = []
        for e in emps:
            r = last.get(e["id"])
            if r is None:
                status = "not_tested"
            elif r["vid"] != doc["active_version_id"] and r["passed"] and (
                    r["vid"] in changed_versions or self._older_than_changes(document_id, r["vid"])):
                status = "retest"
            else:
                status = "passed" if r["passed"] else "failed"
            out.append({"employee_id": e["id"], "full_name": e["full_name"], "department_name": e["department_name"],
                        "position": e["position"], "status": status,
                        "date": r["finished_at"] if r else None, "percent": r["percent"] if r else None,
                        "version_no": r["vno"] if r else None})
        return out

    def _older_than_changes(self, document_id: int, version_id: int | None) -> bool:
        if version_id is None:
            return False
        vno = self.db.scalar("SELECT version_no FROM document_versions WHERE id = ?", (version_id,))
        return bool(self.db.scalar(
            "SELECT COUNT(*) FROM document_changes c JOIN document_versions v ON v.id = c.new_version_id "
            "WHERE v.document_id = ? AND v.version_no > ? AND v.status IN ('active','superseded') "
            "AND c.change_type IN ('added','modified','removed','manual')", (document_id, vno)))

    def not_tested_mandatory(self) -> int:
        """Число пар «сотрудник × обязательный действующий документ» без успешного прохождения."""
        total = 0
        for d in self.db.query("SELECT id FROM documents WHERE is_mandatory = 1 AND status IN ('active','revision_review','pending_update') "
                               "AND active_version_id IS NOT NULL"):
            total += sum(1 for r in self.control(d["id"]) if r["status"] in ("not_tested", "retest", "failed"))
        return total

    def dashboard(self) -> dict:
        q = self.db.scalar
        return {
            "documents": q("SELECT COUNT(*) FROM documents"),
            "active_documents": q("SELECT COUNT(*) FROM documents WHERE status = 'active'"),
            "approved_questions": q("SELECT COUNT(*) FROM questions q JOIN documents d ON d.id = q.document_id "
                                    "WHERE q.status = 'approved' AND q.version_id = d.active_version_id"),
            "tested_employees": q("SELECT COUNT(DISTINCT employee_id) FROM test_sessions WHERE status <> 'in_progress'"),
            "tests": q("SELECT COUNT(*) FROM test_results"),
            "avg_percent": round(q("SELECT AVG(percent) FROM test_results") or 0, 1),
            "pending_questions": q("SELECT COUNT(*) FROM questions WHERE status IN ('review','draft')"),
            "pending_documents": [dict(r) for r in self.db.query(
                "SELECT id, title, status FROM documents WHERE status IN ('revision_review','pending_update') ORDER BY title")],
            "recent": self.list(ResultFilter(), limit=10),
        }
