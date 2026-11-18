"""База вопросов: хранение, редактирование, утверждение."""
from __future__ import annotations

import re

from ibtest.database.connection import Database
from ibtest.models.common import (DIFFICULTIES, OptionData, QStatus, QType, QuestionData, TRUE_FALSE_LABELS,
                                  new_uid, now_iso)
from ibtest.services.security.auth import AuditLog


class QuestionError(Exception):
    def __init__(self, key: str, **kw):
        super().__init__(key)
        self.key, self.kw = key, kw


def norm_question_text(text: str) -> str:
    t = text.lower().replace("ё", "е")
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def validate_question(q: QuestionData) -> list[str]:
    """Структурная проверка вопроса. Возвращает ключи ошибок."""
    errs = []
    if q.qtype not in QType.ALL:
        errs.append("q_bad_type")
    if len(q.text.strip()) < 10:
        errs.append("q_text_short")
    texts = [o.text.strip() for o in q.options]
    if any(not t for t in texts):
        errs.append("q_empty_option")
    if len({norm_question_text(t) for t in texts}) != len(texts):
        errs.append("q_duplicate_options")
    correct = sum(1 for o in q.options if o.is_correct)
    if q.qtype in (QType.SINGLE, QType.SITUATIONAL):
        if len(q.options) < 3 or len(q.options) > 6:
            errs.append("q_options_count")
        if correct != 1:
            errs.append("q_need_one_correct")
    elif q.qtype == QType.MULTIPLE:
        if len(q.options) < 4 or len(q.options) > 7:
            errs.append("q_options_count")
        if correct < 2 or correct == len(q.options):
            errs.append("q_need_multi_correct")
    elif q.qtype == QType.TRUEFALSE:
        if len(q.options) != 2 or correct != 1:
            errs.append("q_truefalse_shape")
    if q.difficulty not in DIFFICULTIES:
        errs.append("q_bad_difficulty")
    lowered = " ".join(texts).lower()
    if any(p in lowered for p in ("все перечисленное", "все перечисленные", "все вышеперечисленное",
                                   "ничего из перечисленного", "барлығы дұрыс", "жоғарыдағылардың барлығы")):
        errs.append("q_all_of_above")
    return errs


class QuestionService:
    def __init__(self, db: Database, audit: AuditLog):
        self.db, self.audit = db, audit

    # -- создание -----------------------------------------------------------
    def create(self, q: QuestionData, document_id: int, version_id: int, section_id: int | None = None,
               requirement_id: int | None = None, status: str = QStatus.REVIEW, origin: str = "ai",
               parent_question_id: int | None = None, review_note: str | None = None,
               check: bool = True) -> int:
        if q.qtype == QType.TRUEFALSE and not q.options:
            labels = TRUE_FALSE_LABELS[q.language]
            q.options = [OptionData(labels[0], True), OptionData(labels[1], False)]
        if check:
            errs = validate_question(q)
            if errs:
                raise QuestionError(errs[0])
        ts = now_iso()
        with self.db.transaction():
            cur = self.db.execute(
                "INSERT INTO questions(uid, document_id, version_id, section_id, requirement_id, parent_question_id, "
                "qtype, text, explanation, section_number, source_text, language, difficulty, status, origin, "
                "review_note, norm_text, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_uid("q_"), document_id, version_id, section_id, requirement_id, parent_question_id, q.qtype,
                 q.text.strip(), q.explanation.strip(), q.section_number, q.source_text, q.language, q.difficulty,
                 status, origin, review_note, norm_question_text(q.text), ts, ts))
            qid = cur.lastrowid
            self._write_options(qid, q.options)
            self.db.execute("INSERT INTO question_approvals(question_id, admin_id, action, from_status, to_status, "
                            "created_at) VALUES (?,?,?,?,?,?)",
                            (qid, self.audit.current.id if self.audit.current else None, "create", None, status, ts))
        return qid

    def _write_options(self, qid: int, options: list[OptionData]) -> None:
        self.db.execute("DELETE FROM question_options WHERE question_id = ?", (qid,))
        for i, o in enumerate(options):
            self.db.execute("INSERT INTO question_options(question_id, order_index, text, is_correct) VALUES (?,?,?,?)",
                            (qid, i, o.text.strip(), int(bool(o.is_correct))))

    # -- чтение -------------------------------------------------------------
    def get(self, qid: int):
        return self.db.one(
            "SELECT q.*, d.title AS document_title, v.version_no, s.text AS section_text "
            "FROM questions q JOIN documents d ON d.id = q.document_id "
            "JOIN document_versions v ON v.id = q.version_id "
            "LEFT JOIN document_sections s ON s.id = q.section_id WHERE q.id = ?", (qid,))

    def options(self, qid: int) -> list:
        return self.db.query("SELECT * FROM question_options WHERE question_id = ? ORDER BY order_index", (qid,))

    def as_data(self, qid: int) -> QuestionData:
        r = self.get(qid)
        return QuestionData(qtype=r["qtype"], text=r["text"],
                            options=[OptionData(o["text"], bool(o["is_correct"])) for o in self.options(qid)],
                            explanation=r["explanation"] or "", section_number=r["section_number"] or "",
                            source_text=r["source_text"] or "", language=r["language"], difficulty=r["difficulty"])

    def list(self, document_id: int | None = None, version_id: int | None = None, status: str | None = None,
             statuses: tuple[str, ...] | None = None, search: str = "", qtype: str | None = None,
             difficulty: str | None = None, language: str | None = None, limit: int = 5000) -> list:
        sql = ("SELECT q.*, d.title AS document_title, v.version_no, v.status AS version_status, "
               "(SELECT COUNT(*) FROM question_options o WHERE o.question_id = q.id) AS option_count "
               "FROM questions q JOIN documents d ON d.id = q.document_id "
               "JOIN document_versions v ON v.id = q.version_id WHERE 1=1")
        p: list = []
        if document_id:
            sql += " AND q.document_id = ?"
            p.append(document_id)
        if version_id:
            sql += " AND q.version_id = ?"
            p.append(version_id)
        if status:
            sql += " AND q.status = ?"
            p.append(status)
        if statuses:
            sql += f" AND q.status IN ({','.join('?' * len(statuses))})"
            p += list(statuses)
        if qtype:
            sql += " AND q.qtype = ?"
            p.append(qtype)
        if difficulty:
            sql += " AND q.difficulty = ?"
            p.append(difficulty)
        if language:
            sql += " AND q.language = ?"
            p.append(language)
        if search:
            sql += " AND (q.norm_text LIKE ? OR q.section_number LIKE ?)"
            p += [f"%{norm_question_text(search)}%", f"%{search}%"]
        sql += " ORDER BY d.title, v.version_no, q.section_number, q.id LIMIT ?"
        p.append(limit)
        return self.db.query(sql, tuple(p))

    def approvals(self, qid: int) -> list:
        return self.db.query("SELECT a.*, u.username FROM question_approvals a LEFT JOIN admin_users u "
                             "ON u.id = a.admin_id WHERE a.question_id = ? ORDER BY a.id", (qid,))

    def find_duplicate(self, version_id: int, text: str, threshold: float = 0.85) -> int | None:
        """Ищет практически одинаковый вопрос в той же редакции (сходство слов)."""
        norm = norm_question_text(text)
        words = set(norm.split())
        if not words:
            return None
        for r in self.db.query("SELECT id, norm_text FROM questions WHERE version_id = ? AND status <> 'rejected'",
                               (version_id,)):
            if r["norm_text"] == norm:
                return r["id"]
            other = set(r["norm_text"].split())
            if other and len(words & other) / len(words | other) >= threshold:
                return r["id"]
        return None

    # -- изменение ------------------------------------------------------------
    def update(self, qid: int, q: QuestionData, note: str = "") -> None:
        errs = validate_question(q)
        if errs:
            raise QuestionError(errs[0])
        old = self.get(qid)
        if old is None:
            raise QuestionError("q_not_found")
        new_status = old["status"]
        if old["status"] == QStatus.APPROVED:
            # Изменённый утверждённый вопрос требует повторного утверждения.
            new_status = QStatus.REVIEW
        with self.db.transaction():
            self.db.execute("UPDATE questions SET qtype=?, text=?, explanation=?, section_number=?, difficulty=?, "
                            "language=?, norm_text=?, status=?, updated_at=? WHERE id=?",
                            (q.qtype, q.text.strip(), q.explanation.strip(), q.section_number, q.difficulty,
                             q.language, norm_question_text(q.text), new_status, now_iso(), qid))
            self._write_options(qid, q.options)
            self._approval(qid, "edit", old["status"], new_status, note)
        self.audit.log("question_edit", "questions", qid)

    def set_status(self, qids: list[int], status: str, comment: str = "") -> int:
        if status not in QStatus.ALL:
            raise QuestionError("q_bad_status")
        changed = 0
        with self.db.transaction():
            for qid in qids:
                row = self.db.one("SELECT status, version_id FROM questions WHERE id = ?", (qid,))
                if row is None or row["status"] == status:
                    continue
                if status == QStatus.APPROVED:
                    errs = validate_question(self.as_data(qid))
                    if errs:
                        raise QuestionError("q_cannot_approve_invalid", qid=qid, err=errs[0])
                self.db.execute("UPDATE questions SET status = ?, previous_status = NULL, updated_at = ? WHERE id = ?",
                                (status, now_iso(), qid))
                self._approval(qid, {"approved": "approve", "rejected": "reject", "review": "submit",
                                     "obsolete": "obsolete", "draft": "to_draft"}[status], row["status"], status, comment)
                changed += 1
        self.audit.log(f"question_{status}", "questions", ",".join(map(str, qids[:50])), {"count": changed})
        return changed

    def delete(self, qids: list[int]) -> int:
        n = 0
        with self.db.transaction():
            for qid in qids:
                self.db.execute("DELETE FROM questions WHERE id = ?", (qid,))
                n += 1
        self.audit.log("question_delete", "questions", ",".join(map(str, qids[:50])), {"count": n})
        return n

    def _approval(self, qid, action, from_s, to_s, comment=""):
        self.db.execute("INSERT INTO question_approvals(question_id, admin_id, action, from_status, to_status, comment, "
                        "created_at) VALUES (?,?,?,?,?,?,?)",
                        (qid, self.audit.current.id if self.audit.current else None, action, from_s, to_s,
                         comment or None, now_iso()))

    def copy_to_version(self, qid: int, version_id: int, section_id: int | None, status: str, note: str | None) -> int:
        """Перенос вопроса в новую редакцию (новая запись; история старой сохраняется)."""
        src = self.get(qid)
        data = self.as_data(qid)
        new_id = self.create(data, src["document_id"], version_id, section_id, None, status=status, origin="carried",
                             parent_question_id=qid, review_note=note, check=False)
        return new_id

    # -- статистика -----------------------------------------------------------
    def counts_by_status(self, document_id: int | None = None) -> dict[str, int]:
        sql = "SELECT status, COUNT(*) c FROM questions"
        p: tuple = ()
        if document_id:
            sql += " WHERE document_id = ?"
            p = (document_id,)
        out = {s: 0 for s in QStatus.ALL}
        for r in self.db.query(sql + " GROUP BY status", p):
            out[r["status"]] = r["c"]
        return out

    def usable_count(self, document_id: int) -> int:
        """Количество утверждённых вопросов действующей редакции."""
        return self.db.scalar(
            "SELECT COUNT(*) FROM questions q JOIN documents d ON d.id = q.document_id "
            "WHERE q.document_id = ? AND q.version_id = d.active_version_id AND q.status = 'approved'",
            (document_id,)) or 0
