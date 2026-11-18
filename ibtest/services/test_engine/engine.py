"""Формирование и проведение тестирования."""
from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from ibtest.database.connection import Database
from ibtest.models.common import QType, new_uid, now_iso
from ibtest.services.security.auth import AuditLog


class TestBuildError(Exception):
    __test__ = False

    def __init__(self, key: str, **kw):
        super().__init__(key)
        self.key, self.kw = key, kw


DIFF_TARGET = {"easy": 0.3, "medium": 0.5, "hard": 0.2}


@dataclass
class SessionQuestion:
    id: int
    order_index: int
    qtype: str
    text: str
    options: list[dict]   # [{"text":..., "correct": bool}]
    document_title: str
    section_number: str


# ---------------------------------------------------------------- профили
class ProfileService:
    def __init__(self, db: Database, audit: AuditLog):
        self.db, self.audit = db, audit

    def list(self, active_only: bool = False) -> list:
        sql = "SELECT * FROM test_profiles"
        if active_only:
            sql += " WHERE is_active = 1"
        return self.db.query(sql + " ORDER BY is_default DESC, name")

    def get(self, pid: int):
        return self.db.one("SELECT * FROM test_profiles WHERE id = ?", (pid,))

    def documents(self, pid: int) -> list:
        return self.db.query("SELECT pd.*, d.title, d.status FROM test_profile_documents pd JOIN documents d "
                             "ON d.id = pd.document_id WHERE pd.profile_id = ? ORDER BY d.title", (pid,))

    def default(self):
        return self.db.one("SELECT * FROM test_profiles WHERE is_active = 1 ORDER BY is_default DESC, id LIMIT 1")

    def save(self, pid: int | None, name: str, question_count: int, time_limit_min: int, pass_score: int,
             language: str | None, insufficient_policy: str, docs: list[tuple[int, int]], is_default: bool,
             is_active: bool = True) -> int:
        name = name.strip()
        if not name:
            raise TestBuildError("profile_name_empty")
        if not docs:
            raise TestBuildError("profile_no_documents")
        if sum(c for _, c in docs) != question_count:
            raise TestBuildError("profile_counts_mismatch", total=sum(c for _, c in docs), need=question_count)
        if not 1 <= pass_score <= 100:
            raise TestBuildError("profile_bad_pass")
        with self.db.transaction():
            if is_default:
                self.db.execute("UPDATE test_profiles SET is_default = 0")
            if pid:
                self.db.execute("UPDATE test_profiles SET name=?, question_count=?, time_limit_min=?, pass_score=?, "
                                "language=?, insufficient_policy=?, is_default=?, is_active=? WHERE id=?",
                                (name, question_count, time_limit_min, pass_score, language, insufficient_policy,
                                 int(is_default), int(is_active), pid))
                self.db.execute("DELETE FROM test_profile_documents WHERE profile_id = ?", (pid,))
            else:
                cur = self.db.execute("INSERT INTO test_profiles(name, question_count, time_limit_min, pass_score, "
                                      "language, insufficient_policy, is_default, is_active, created_at) "
                                      "VALUES (?,?,?,?,?,?,?,?,?)",
                                      (name, question_count, time_limit_min, pass_score, language,
                                       insufficient_policy, int(is_default), int(is_active), now_iso()))
                pid = cur.lastrowid
            for doc_id, cnt in docs:
                self.db.execute("INSERT INTO test_profile_documents(profile_id, document_id, question_count) "
                                "VALUES (?,?,?)", (pid, doc_id, cnt))
        self.audit.log("profile_save", "test_profiles", pid, {"name": name, "count": question_count,
                                                             "docs": docs, "pass": pass_score})
        return pid

    def delete(self, pid: int) -> None:
        self.db.execute("DELETE FROM test_profiles WHERE id = ?", (pid,))
        self.audit.log("profile_delete", "test_profiles", pid)

    def readiness(self, pid: int) -> list[dict]:
        """Для каждого документа профиля: сколько нужно и сколько доступно вопросов."""
        prof = self.get(pid)
        out = []
        for d in self.documents(pid):
            avail = _pool_query(self.db, d["document_id"], prof["language"])
            doc = self.db.one("SELECT status FROM documents WHERE id = ?", (d["document_id"],))
            out.append({"document_id": d["document_id"], "title": d["title"], "need": d["question_count"],
                        "available": len(avail), "doc_status": doc["status"]})
        return out


def _pool_query(db: Database, document_id: int, language: str | None) -> list:
    """Вопросы, допустимые в тестировании: утверждённые, действующей редакции,
    документ не архивный и не утративший силу."""
    sql = ("SELECT q.*, d.title AS document_title, v.version_no, s.top_group "
           "FROM questions q JOIN documents d ON d.id = q.document_id "
           "JOIN document_versions v ON v.id = q.version_id "
           "LEFT JOIN document_sections s ON s.id = q.section_id "
           "WHERE q.document_id = ? AND q.version_id = d.active_version_id AND v.status = 'active' "
           "AND q.status = 'approved' AND d.status IN ('active','revision_review','pending_update')")
    params: list = [document_id]
    if language:
        sql += " AND q.language = ?"
        params.append(language)
    return db.query(sql, tuple(params))


def balanced_sample(pool: list, n: int, rng: random.Random) -> list:
    """Случайная выборка, сбалансированная по разделам документа и сложности."""
    if n >= len(pool):
        out = list(pool)
        rng.shuffle(out)
        return out
    groups: dict[str, list] = defaultdict(list)
    for q in pool:
        groups[q["top_group"] or q["section_number"] or "-"].append(q)
    for g in groups.values():
        rng.shuffle(g)
    keys = list(groups)
    rng.shuffle(keys)
    # Квоты пропорционально размеру раздела (метод наибольших остатков), но не менее 1,
    # пока хватает мест.
    total = len(pool)
    raw = {k: n * len(groups[k]) / total for k in keys}
    quota = {k: int(raw[k]) for k in keys}
    if n >= len(keys):
        for k in keys:
            quota[k] = max(1, quota[k])
    while sum(quota.values()) > n:
        k = max((k for k in keys if quota[k] > 1), key=lambda k: quota[k] - raw[k], default=None)
        if k is None:
            break
        quota[k] -= 1
    rest = n - sum(quota.values())
    for k in sorted(keys, key=lambda k: raw[k] - int(raw[k]), reverse=True):
        if rest <= 0:
            break
        if quota[k] < len(groups[k]):
            quota[k] += 1
            rest -= 1
    chosen: list = []
    for k in keys:
        chosen += _pick_by_difficulty(groups[k], min(quota[k], len(groups[k])), rng)
    if len(chosen) < n:
        taken = {q["id"] for q in chosen}
        left = [q for q in pool if q["id"] not in taken]
        rng.shuffle(left)
        chosen += left[:n - len(chosen)]
    chosen = chosen[:n]
    rng.shuffle(chosen)
    return chosen


def _pick_by_difficulty(items: list, k: int, rng: random.Random) -> list:
    by: dict[str, list] = defaultdict(list)
    for q in items:
        by[q["difficulty"]].append(q)
    out = []
    want = {d: round(k * share) for d, share in DIFF_TARGET.items()}
    for d, cnt in want.items():
        out += by[d][:cnt]
        by[d] = by[d][cnt:]
    rest = [q for d in by for q in by[d]]
    rng.shuffle(rest)
    out += rest[:max(0, k - len(out))]
    return out[:k]


# ---------------------------------------------------------------- тестирование
class TestEngine:
    __test__ = False

    def __init__(self, db: Database, audit: AuditLog, rng: random.Random | None = None):
        self.db, self.audit = db, audit
        self.rng = rng or random.SystemRandom()

    def build(self, profile_id: int, employee_id: int) -> int:
        """Создаёт сессию тестирования. Возвращает id сессии."""
        prof = self.db.one("SELECT * FROM test_profiles WHERE id = ? AND is_active = 1", (profile_id,))
        if prof is None:
            raise TestBuildError("profile_not_found")
        emp = self.db.one("SELECT e.*, d.name AS dept FROM employees e JOIN departments d ON d.id = e.department_id "
                          "WHERE e.id = ?", (employee_id,))
        if emp is None:
            raise TestBuildError("employee_not_found")
        docs = self.db.query("SELECT * FROM test_profile_documents WHERE profile_id = ?", (profile_id,))
        if not docs:
            raise TestBuildError("profile_no_documents")
        pools = {}
        shortages = []
        for d in docs:
            pool = _pool_query(self.db, d["document_id"], prof["language"])
            pools[d["document_id"]] = pool
            if len(pool) < d["question_count"]:
                title = self.db.scalar("SELECT title FROM documents WHERE id = ?", (d["document_id"],))
                shortages.append((title, d["question_count"], len(pool)))
        if shortages and prof["insufficient_policy"] == "block":
            raise TestBuildError("not_enough_questions", items=shortages)
        if all(len(p) == 0 for p in pools.values()):
            raise TestBuildError("not_enough_questions", items=shortages)

        # Не повторять тот же набор вопросов в том же порядке, что недавно.
        recent = {r["question_set_hash"] for r in self.db.query(
            "SELECT question_set_hash FROM test_sessions WHERE employee_id = ? ORDER BY id DESC LIMIT 20",
            (employee_id,))}
        for _attempt in range(25):
            chosen = []
            for d in docs:
                chosen += balanced_sample(pools[d["document_id"]], min(d["question_count"],
                                                                       len(pools[d["document_id"]])), self.rng)
            self.rng.shuffle(chosen)
            set_hash = hashlib.sha256(",".join(q["uid"] for q in chosen).encode()).hexdigest()
            if set_hash not in recent:
                break
        lang = prof["language"] or (chosen[0]["language"] if chosen else "ru")
        ts = now_iso()
        with self.db.transaction():
            cur = self.db.execute(
                "INSERT INTO test_sessions(uid, employee_id, profile_id, profile_name, employee_name, department_name, "
                "position, language, question_count, pass_score, time_limit_min, question_set_hash, started_at, status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'in_progress')",
                (new_uid("s_"), employee_id, profile_id, prof["name"], emp["full_name"], emp["dept"], emp["position"],
                 lang, len(chosen), prof["pass_score"], prof["time_limit_min"], set_hash, ts))
            sid = cur.lastrowid
            for i, q in enumerate(chosen):
                opts = self.db.query("SELECT text, is_correct FROM question_options WHERE question_id = ? "
                                     "ORDER BY order_index", (q["id"],))
                opts = [{"text": o["text"], "correct": bool(o["is_correct"])} for o in opts]
                if q["qtype"] != QType.TRUEFALSE:
                    self.rng.shuffle(opts)
                self.db.execute(
                    "INSERT INTO test_questions(session_id, order_index, question_id, question_uid, document_id, "
                    "version_id, document_title, version_no, section_number, qtype, difficulty, text, options_json, "
                    "explanation) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, i, q["id"], q["uid"], q["document_id"], q["version_id"], q["document_title"], q["version_no"],
                     q["section_number"], q["qtype"], q["difficulty"], q["text"], json.dumps(opts, ensure_ascii=False),
                     q["explanation"]))
        return sid

    def questions(self, session_id: int) -> list[SessionQuestion]:
        rows = self.db.query("SELECT * FROM test_questions WHERE session_id = ? ORDER BY order_index", (session_id,))
        return [SessionQuestion(r["id"], r["order_index"], r["qtype"], r["text"], json.loads(r["options_json"]),
                                r["document_title"], r["section_number"] or "") for r in rows]

    def session(self, session_id: int):
        return self.db.one("SELECT * FROM test_sessions WHERE id = ?", (session_id,))

    def answers(self, session_id: int) -> dict[int, list[int]]:
        rows = self.db.query("SELECT a.test_question_id, a.selected_json FROM employee_answers a "
                             "JOIN test_questions q ON q.id = a.test_question_id WHERE q.session_id = ?", (session_id,))
        return {r["test_question_id"]: json.loads(r["selected_json"]) for r in rows}

    def answer(self, session_id: int, test_question_id: int, selected: list[int]) -> None:
        s = self.session(session_id)
        if s is None or s["status"] != "in_progress":
            raise TestBuildError("session_closed")
        if self._expired(s):
            raise TestBuildError("session_time_over")
        tq = self.db.one("SELECT id FROM test_questions WHERE id = ? AND session_id = ?", (test_question_id, session_id))
        if tq is None:
            raise TestBuildError("question_not_in_session")
        sel = sorted({int(i) for i in selected})
        if sel:
            self.db.execute("INSERT INTO employee_answers(test_question_id, selected_json, answered_at) VALUES (?,?,?) "
                            "ON CONFLICT(test_question_id) DO UPDATE SET selected_json = excluded.selected_json, "
                            "answered_at = excluded.answered_at", (test_question_id, json.dumps(sel), now_iso()))
        else:
            self.db.execute("DELETE FROM employee_answers WHERE test_question_id = ?", (test_question_id,))

    @staticmethod
    def _expired(s) -> bool:
        if not s["time_limit_min"]:
            return False
        started = datetime.fromisoformat(s["started_at"])
        # Небольшой запас на задержку интерфейса.
        return (datetime.now() - started).total_seconds() > s["time_limit_min"] * 60 + 5

    def remaining_seconds(self, session_id: int) -> int | None:
        s = self.session(session_id)
        if not s["time_limit_min"]:
            return None
        started = datetime.fromisoformat(s["started_at"])
        return max(0, int(s["time_limit_min"] * 60 - (datetime.now() - started).total_seconds()))

    def finish(self, session_id: int, expired: bool = False) -> dict:
        s = self.session(session_id)
        if s is None:
            raise TestBuildError("session_not_found")
        if s["status"] != "in_progress":
            return self.result(session_id)
        if self._expired(s):
            expired = True
        qs = self.db.query("SELECT * FROM test_questions WHERE session_id = ? ORDER BY order_index", (session_id,))
        ans = self.answers(session_id)
        correct = wrong = unanswered = 0
        ts = now_iso()
        with self.db.transaction():
            for q in qs:
                opts = json.loads(q["options_json"])
                right = sorted(i for i, o in enumerate(opts) if o["correct"])
                sel = ans.get(q["id"])
                if sel is None:
                    unanswered += 1
                    continue
                ok = sel == right
                correct += ok
                wrong += not ok
                self.db.execute("UPDATE employee_answers SET is_correct = ? WHERE test_question_id = ?", (int(ok), q["id"]))
            total = len(qs)
            percent = round(correct * 100.0 / total, 1) if total else 0.0
            passed = percent >= s["pass_score"]
            duration = int((datetime.fromisoformat(ts) - datetime.fromisoformat(s["started_at"])).total_seconds())
            payload = json.dumps({"session": s["uid"], "answers": {str(k): v for k, v in sorted(ans.items())},
                                  "correct": correct, "total": total, "finished": ts}, sort_keys=True)
            ihash = hashlib.sha256(payload.encode()).hexdigest()
            self.db.execute("INSERT INTO test_results(session_id, total, correct, wrong, unanswered, percent, passed, "
                            "integrity_hash, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                            (session_id, total, correct, wrong + unanswered, unanswered, percent, int(passed), ihash, ts))
            self.db.execute("UPDATE test_sessions SET status = ?, finished_at = ?, duration_sec = ? WHERE id = ?",
                            ("expired" if expired else "finished", ts, duration, session_id))
        return self.result(session_id)

    def abort_stale(self) -> int:
        """Незавершённые сессии с истёкшим временем (например, после сбоя питания)
        завершаются с подсчётом имеющихся ответов."""
        n = 0
        for s in self.db.query("SELECT * FROM test_sessions WHERE status = 'in_progress'"):
            started = datetime.fromisoformat(s["started_at"])
            limit = (s["time_limit_min"] or 240) * 60
            if (datetime.now() - started).total_seconds() > limit + 60:
                self.finish(s["id"], expired=True)
                n += 1
        return n

    def result(self, session_id: int) -> dict:
        r = self.db.one("SELECT s.*, r.total, r.correct, r.wrong, r.unanswered, r.percent, r.passed, r.integrity_hash "
                        "FROM test_sessions s JOIN test_results r ON r.session_id = s.id WHERE s.id = ?", (session_id,))
        return dict(r) if r else {}

    def review(self, session_id: int) -> list[dict]:
        """Разбор теста: вопрос, варианты, выбранные и правильные ответы (только после завершения)."""
        s = self.session(session_id)
        if s is None or s["status"] == "in_progress":
            raise TestBuildError("session_not_finished")
        ans = self.answers(session_id)
        out = []
        for q in self.db.query("SELECT * FROM test_questions WHERE session_id = ? ORDER BY order_index", (session_id,)):
            opts = json.loads(q["options_json"])
            out.append({"order": q["order_index"] + 1, "text": q["text"], "qtype": q["qtype"], "options": opts,
                        "selected": ans.get(q["id"], []), "correct": [i for i, o in enumerate(opts) if o["correct"]],
                        "explanation": q["explanation"], "document": q["document_title"], "version_no": q["version_no"],
                        "section": q["section_number"]})
        return out

    def verify_integrity(self, session_id: int) -> bool:
        s = self.session(session_id)
        r = self.db.one("SELECT * FROM test_results WHERE session_id = ?", (session_id,))
        if s is None or r is None:
            return False
        ans = self.answers(session_id)
        payload = json.dumps({"session": s["uid"], "answers": {str(k): v for k, v in sorted(ans.items())},
                              "correct": r["correct"], "total": r["total"], "finished": r["created_at"]}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest() == r["integrity_hash"]
