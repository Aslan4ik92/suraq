"""Нормативные документы и управление редакциями."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from ibtest.config import paths
from ibtest.database.connection import Database
from ibtest.models.common import DocStatus, QStatus, VersionStatus, new_uid, now_iso
from ibtest.services.document_parser.parser import DocumentParser, ParsedDocument, extract_requisites
from ibtest.services.document_parser.sections import split_sections, text_hash
from ibtest.services.language.detector import detect_language
from ibtest.services.questions import QuestionService
from ibtest.services.security.auth import AuditLog
from ibtest.services.security.crypto import sha256_file
from ibtest.services.version_comparator import comparator as cmp


class DocumentError(Exception):
    def __init__(self, key: str, **kw):
        super().__init__(key)
        self.key, self.kw = key, kw


@dataclass
class DuplicateInfo:
    document_id: int
    title: str
    version_no: int
    same_file: bool


@dataclass
class RevisionResult:
    version_id: int
    summary: dict
    carried_approved: int
    carried_review: int
    sections_to_generate: list[int]


class DocumentService:
    def __init__(self, db: Database, audit: AuditLog, parser: DocumentParser, questions: QuestionService):
        self.db, self.audit, self.parser, self.questions = db, audit, parser, questions

    # -- чтение ----------------------------------------------------------------
    def list(self, search: str = "", status: str | None = None, include_archived: bool = True) -> list:
        sql = ("SELECT d.*, v.version_no AS active_version_no, "
               "(SELECT COUNT(*) FROM document_versions x WHERE x.document_id = d.id) AS version_count, "
               "(SELECT COUNT(*) FROM questions q WHERE q.document_id = d.id AND q.version_id = d.active_version_id "
               " AND q.status = 'approved') AS approved_count, "
               "(SELECT COUNT(*) FROM questions q WHERE q.document_id = d.id AND q.status IN ('review','draft')) AS review_count "
               "FROM documents d LEFT JOIN document_versions v ON v.id = d.active_version_id WHERE 1=1")
        p: list = []
        if search:
            sql += " AND (d.title LIKE ? OR d.doc_number LIKE ?)"
            p += [f"%{search}%", f"%{search}%"]
        if status:
            sql += " AND d.status = ?"
            p.append(status)
        elif not include_archived:
            sql += " AND d.status NOT IN ('archived','revoked')"
        return self.db.query(sql + " ORDER BY d.updated_at DESC", tuple(p))

    def get(self, doc_id: int):
        return self.db.one("SELECT * FROM documents WHERE id = ?", (doc_id,))

    def versions(self, doc_id: int) -> list:
        return self.db.query(
            "SELECT v.id, v.uid, v.document_id, v.version_no, v.file_name, v.stored_path, v.file_sha256, v.text_sha256, "
            "v.language, v.doc_number, v.doc_date, v.effective_date, v.ocr_used, v.status, v.analysis_state, v.note, "
            "v.created_at, v.activated_at, "
            "(SELECT COUNT(*) FROM questions q WHERE q.version_id = v.id) AS question_count, "
            "(SELECT COUNT(*) FROM questions q WHERE q.version_id = v.id AND q.status='approved') AS approved_count, "
            "(SELECT COUNT(*) FROM document_sections s WHERE s.version_id = v.id) AS section_count "
            "FROM document_versions v WHERE v.document_id = ? ORDER BY v.version_no DESC", (doc_id,))

    def version(self, version_id: int):
        return self.db.one("SELECT * FROM document_versions WHERE id = ?", (version_id,))

    def sections(self, version_id: int) -> list:
        return self.db.query("SELECT * FROM document_sections WHERE version_id = ? ORDER BY order_index", (version_id,))

    def changes(self, new_version_id: int) -> list:
        return self.db.query(
            "SELECT c.*, so.number AS old_number, so.text AS old_text, sn.number AS new_number, sn.text AS new_text "
            "FROM document_changes c LEFT JOIN document_sections so ON so.id = c.old_section_id "
            "LEFT JOIN document_sections sn ON sn.id = c.new_section_id WHERE c.new_version_id = ? "
            "ORDER BY COALESCE(sn.order_index, so.order_index + 0.5)", (new_version_id,))

    # -- загрузка ----------------------------------------------------------------
    def parse_file(self, path: Path, progress=None, force_ocr: bool = False) -> ParsedDocument:
        return self.parser.parse(path, progress, force_ocr)

    def find_duplicate(self, path: Path, text: str) -> DuplicateInfo | None:
        fh, th = sha256_file(path), text_hash(text)
        row = self.db.one("SELECT v.document_id, v.version_no, v.file_sha256, d.title FROM document_versions v "
                          "JOIN documents d ON d.id = v.document_id WHERE v.file_sha256 = ? OR v.text_sha256 = ? "
                          "ORDER BY v.file_sha256 = ? DESC LIMIT 1", (fh, th, fh))
        if row:
            return DuplicateInfo(row["document_id"], row["title"], row["version_no"], row["file_sha256"] == fh)
        return None

    def _store_file(self, src: Path, doc_uid: str, version_no: int, sha: str) -> Path:
        target_dir = paths.documents_dir() / doc_uid
        target_dir.mkdir(parents=True, exist_ok=True)
        dst = target_dir / f"v{version_no}_{sha[:12]}{src.suffix.lower()}"
        shutil.copy2(src, dst)
        if sha256_file(dst) != sha:
            dst.unlink(missing_ok=True)
            raise DocumentError("file_copy_failed")
        return dst

    def _insert_sections(self, version_id: int, text: str) -> list[int]:
        ids = []
        for s in split_sections(text):
            cur = self.db.execute(
                "INSERT INTO document_sections(version_id, order_index, number, heading, text, norm_hash, top_group) "
                "VALUES (?,?,?,?,?,?,?)", (version_id, s.order_index, s.number, s.heading, s.text, s.norm_hash,
                                           s.top_group))
            ids.append(cur.lastrowid)
        return ids

    def import_document(self, path: Path, parsed: ParsedDocument, title: str, doc_number: str = "",
                        doc_date: str = "", effective_date: str = "", language: str | None = None,
                        note: str = "") -> int:
        """Новый документ, редакция № 1 (действующая)."""
        title = " ".join(title.split())
        if not title:
            raise DocumentError("doc_title_empty")
        lang = language or detect_language(parsed.text)
        req = extract_requisites(parsed.text)
        fsha = sha256_file(path)
        doc_uid = new_uid("d_")
        ts = now_iso()
        stored = self._store_file(Path(path), doc_uid, 1, fsha)
        try:
            with self.db.transaction():
                cur = self.db.execute(
                    "INSERT INTO documents(uid, title, doc_number, doc_date, effective_date, language, status, "
                    "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (doc_uid, title, doc_number or req.get("doc_number"), doc_date or req.get("doc_date"),
                     effective_date or None, lang if lang in ("ru", "kk") else "ru", DocStatus.ACTIVE, ts, ts))
                doc_id = cur.lastrowid
                vid = self._insert_version(doc_id, 1, path, stored, fsha, parsed, lang, doc_number or req.get("doc_number"),
                                           doc_date or req.get("doc_date"), effective_date, VersionStatus.ACTIVE, note)
                self.db.execute("UPDATE documents SET active_version_id = ? WHERE id = ?", (vid, doc_id))
                self.db.execute("UPDATE document_versions SET activated_at = ? WHERE id = ?", (ts, vid))
                self._insert_sections(vid, parsed.text)
        except Exception:
            stored.unlink(missing_ok=True)
            raise
        self.audit.log("document_import", "documents", doc_id, {"title": title, "file": Path(path).name,
                                                                "language": lang, "ocr": parsed.ocr_used})
        return doc_id

    def _insert_version(self, doc_id, version_no, src, stored, fsha, parsed, lang, number, date, eff, status, note):
        cur = self.db.execute(
            "INSERT INTO document_versions(uid, document_id, version_no, file_name, stored_path, file_sha256, "
            "text_sha256, raw_text, language, doc_number, doc_date, effective_date, ocr_used, status, note, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_uid("v_"), doc_id, version_no, Path(src).name, str(stored), fsha, text_hash(parsed.text), parsed.text,
             lang if lang in ("ru", "kk") else "ru", number or None, date or None, eff or None, int(parsed.ocr_used),
             status, note or None, now_iso()))
        return cur.lastrowid

    def update_meta(self, doc_id: int, title: str, doc_number: str, doc_date: str, effective_date: str,
                    language: str, is_mandatory: bool) -> None:
        if not title.strip():
            raise DocumentError("doc_title_empty")
        self.db.execute("UPDATE documents SET title=?, doc_number=?, doc_date=?, effective_date=?, language=?, "
                        "is_mandatory=?, updated_at=? WHERE id=?",
                        (" ".join(title.split()), doc_number or None, doc_date or None, effective_date or None,
                         language, int(is_mandatory), now_iso(), doc_id))
        self.audit.log("document_update", "documents", doc_id, {"title": title})

    def set_status(self, doc_id: int, status: str) -> None:
        if status not in DocStatus.ALL:
            raise DocumentError("doc_bad_status")
        self.db.execute("UPDATE documents SET status = ?, updated_at = ? WHERE id = ?", (status, now_iso(), doc_id))
        self.audit.log("document_status", "documents", doc_id, {"status": status})

    def delete_document(self, doc_id: int) -> None:
        """Удаление возможно, только если документ не использовался в тестировании.
        Иначе документ архивируется / помечается утратившим силу."""
        used = self.db.scalar("SELECT COUNT(*) FROM test_questions WHERE document_id = ?", (doc_id,))
        if used:
            raise DocumentError("doc_used_in_tests")
        doc = self.get(doc_id)
        if doc is None:
            return
        files = [r["stored_path"] for r in self.db.query("SELECT stored_path FROM document_versions WHERE document_id=?",
                                                         (doc_id,))]
        with self.db.transaction():
            self.db.execute("DELETE FROM test_profile_documents WHERE document_id = ?", (doc_id,))
            self.db.execute("UPDATE documents SET active_version_id = NULL WHERE id = ?", (doc_id,))
            self.db.execute("DELETE FROM questions WHERE document_id = ?", (doc_id,))
            vids = [r["id"] for r in self.db.query("SELECT id FROM document_versions WHERE document_id = ?", (doc_id,))]
            for vid in vids:
                self.db.execute("DELETE FROM document_changes WHERE new_version_id = ? OR old_version_id = ?", (vid, vid))
                self.db.execute("DELETE FROM requirements WHERE version_id = ?", (vid,))
                self.db.execute("DELETE FROM document_sections WHERE version_id = ?", (vid,))
            self.db.execute("DELETE FROM document_versions WHERE document_id = ?", (doc_id,))
            self.db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        for f in files:
            Path(f).unlink(missing_ok=True)
        shutil.rmtree(paths.documents_dir() / doc["uid"], ignore_errors=True)
        self.audit.log("document_delete", "documents", doc_id, {"title": doc["title"]})

    # -- редакции ------------------------------------------------------------------
    def add_revision(self, doc_id: int, path: Path, parsed: ParsedDocument, doc_number: str = "",
                     doc_date: str = "", effective_date: str = "", note: str = "") -> RevisionResult:
        doc = self.get(doc_id)
        if doc is None:
            raise DocumentError("doc_not_found")
        if self.db.scalar("SELECT COUNT(*) FROM document_versions WHERE document_id = ? AND status = 'review'", (doc_id,)):
            raise DocumentError("revision_already_pending")
        active = self.version(doc["active_version_id"]) if doc["active_version_id"] else None
        th = text_hash(parsed.text)
        if active and active["text_sha256"] == th:
            raise DocumentError("revision_identical")
        lang = detect_language(parsed.text)
        req = extract_requisites(parsed.text)
        fsha = sha256_file(path)
        version_no = (self.db.scalar("SELECT MAX(version_no) FROM document_versions WHERE document_id = ?", (doc_id,)) or 0) + 1
        stored = self._store_file(Path(path), doc["uid"], version_no, fsha)
        carried_ok = carried_review = 0
        to_generate: list[int] = []
        try:
            with self.db.transaction():
                vid = self._insert_version(doc_id, version_no, path, stored, fsha, parsed, lang,
                                           doc_number or req.get("doc_number"), doc_date or req.get("doc_date"),
                                           effective_date, VersionStatus.REVIEW, note)
                new_ids = self._insert_sections(vid, parsed.text)
                if active:
                    old_secs = [cmp.SectionRef(r["id"], r["number"] or "", r["text"], r["norm_hash"])
                                for r in self.sections(active["id"])]
                    new_secs = [cmp.SectionRef(r["id"], r["number"] or "", r["text"], r["norm_hash"])
                                for r in self.sections(vid)]
                    changes = cmp.compare(old_secs, new_secs)
                    for ch in changes:
                        self.db.execute(
                            "INSERT INTO document_changes(new_version_id, old_version_id, old_section_id, new_section_id, "
                            "change_type, similarity, resolved, created_at) VALUES (?,?,?,?,?,?,?,?)",
                            (vid, active["id"], ch.old.id if ch.old else None, ch.new.id if ch.new else None,
                             ch.change_type, ch.similarity, int(ch.change_type != cmp.MANUAL), now_iso()))
                        a, b = self._carry_questions(ch, vid)
                        carried_ok += a
                        carried_review += b
                        if ch.change_type in (cmp.ADDED, cmp.MODIFIED, cmp.MANUAL) and ch.new:
                            to_generate.append(ch.new.id)
                    summary = cmp.summarize(changes)
                else:
                    summary = {cmp.ADDED: len(new_ids)}
                    to_generate = new_ids
                self.db.execute("UPDATE documents SET status = ?, updated_at = ? WHERE id = ?",
                                (DocStatus.REVISION_REVIEW, now_iso(), doc_id))
        except Exception:
            stored.unlink(missing_ok=True)
            raise
        self.audit.log("revision_upload", "document_versions", vid,
                       {"document": doc["title"], "version_no": version_no, "changes": summary})
        return RevisionResult(vid, summary, carried_ok, carried_review, to_generate)

    def _carry_questions(self, ch: cmp.Change, new_vid: int) -> tuple[int, int]:
        """Перенос вопросов старой редакции в новую по результатам сравнения."""
        if ch.old is None or ch.new is None:
            return 0, 0
        rows = self.db.query("SELECT id, status FROM questions WHERE section_id = ? AND status IN ('approved','review','draft')",
                             (ch.old.id,))
        ok = rev = 0
        for r in rows:
            if ch.change_type == cmp.UNCHANGED and r["status"] == QStatus.APPROVED:
                new_q = self.questions.copy_to_version(r["id"], new_vid, ch.new.id, QStatus.APPROVED, None)
                self.db.execute("UPDATE questions SET section_number = ? WHERE id = ?", (ch.new.number, new_q))
                ok += 1
            else:
                note = {"unchanged": "carried_unchanged", "modified": "carried_modified",
                        "manual": "carried_manual"}[ch.change_type]
                new_q = self.questions.copy_to_version(r["id"], new_vid, ch.new.id, QStatus.REVIEW, note)
                self.db.execute("UPDATE questions SET section_number = ? WHERE id = ?", (ch.new.number, new_q))
                rev += 1
        return ok, rev

    def resolve_change(self, change_id: int, resolution: str) -> None:
        """Ручное решение по неоднозначному сопоставлению:
        'same' — пункт изменён (вопросы остаются на проверке),
        'different' — старый пункт удалён, новый добавлен (перенесённые вопросы отклоняются)."""
        ch = self.db.one("SELECT * FROM document_changes WHERE id = ?", (change_id,))
        if ch is None:
            raise DocumentError("change_not_found")
        with self.db.transaction():
            if resolution == "different" and ch["new_section_id"]:
                rows = self.db.query("SELECT q.id FROM questions q JOIN questions p ON p.id = q.parent_question_id "
                                     "WHERE q.version_id = ? AND q.section_id = ? AND p.section_id = ?",
                                     (ch["new_version_id"], ch["new_section_id"], ch["old_section_id"]))
                if rows:
                    self.questions.set_status([r["id"] for r in rows], QStatus.REJECTED, "manual_different")
            self.db.execute("UPDATE document_changes SET resolved = 1, resolution = ? WHERE id = ?",
                            (resolution, change_id))
        self.audit.log("revision_resolve", "document_changes", change_id, {"resolution": resolution})

    def activate_version(self, version_id: int, force: bool = False) -> None:
        v = self.version(version_id)
        if v is None:
            raise DocumentError("version_not_found")
        if v["status"] == VersionStatus.ACTIVE:
            return
        unresolved = self.db.scalar("SELECT COUNT(*) FROM document_changes WHERE new_version_id = ? AND resolved = 0",
                                    (version_id,))
        if unresolved and not force:
            raise DocumentError("revision_unresolved", count=unresolved)
        approved = self.db.scalar("SELECT COUNT(*) FROM questions WHERE version_id = ? AND status = 'approved'",
                                  (version_id,))
        if not approved and not force:
            raise DocumentError("revision_no_approved")
        doc = self.get(v["document_id"])
        with self.db.transaction():
            self._switch_active(doc, version_id)
        self.audit.log("revision_activate", "document_versions", version_id,
                       {"document": doc["title"], "version_no": v["version_no"]})

    def _switch_active(self, doc, version_id: int) -> None:
        ts = now_iso()
        old_vid = doc["active_version_id"]
        if old_vid and old_vid != version_id:
            self.db.execute("UPDATE document_versions SET status = ? WHERE id = ?", (VersionStatus.SUPERSEDED, old_vid))
            # Вопросы прежней редакции больше не используются — помечаются устаревшими
            # с сохранением прежнего статуса для возможного восстановления редакции.
            self.db.execute("UPDATE questions SET previous_status = status, status = 'obsolete', updated_at = ? "
                            "WHERE version_id = ? AND status IN ('approved','review','draft')", (ts, old_vid))
        # Восстановление статусов вопросов активируемой редакции.
        self.db.execute("UPDATE questions SET status = previous_status, previous_status = NULL, updated_at = ? "
                        "WHERE version_id = ? AND status = 'obsolete' AND previous_status IS NOT NULL", (ts, version_id))
        # Другие редакции «на проверке» этого документа остаются на проверке.
        self.db.execute("UPDATE document_versions SET status = ?, activated_at = ? WHERE id = ?",
                        (VersionStatus.ACTIVE, ts, version_id))
        pending = self.db.scalar("SELECT COUNT(*) FROM document_versions WHERE document_id = ? AND status = 'review'",
                                 (doc["id"],))
        self.db.execute("UPDATE documents SET active_version_id = ?, status = ?, updated_at = ?, "
                        "doc_number = COALESCE((SELECT doc_number FROM document_versions WHERE id = ?), doc_number), "
                        "doc_date = COALESCE((SELECT doc_date FROM document_versions WHERE id = ?), doc_date), "
                        "effective_date = COALESCE((SELECT effective_date FROM document_versions WHERE id = ?), effective_date) "
                        "WHERE id = ?",
                        (version_id, DocStatus.REVISION_REVIEW if pending else DocStatus.ACTIVE, ts,
                         version_id, version_id, version_id, doc["id"]))

    def restore_version(self, version_id: int) -> None:
        """Восстановление предыдущей редакции как действующей."""
        v = self.version(version_id)
        if v is None or v["status"] != VersionStatus.SUPERSEDED:
            raise DocumentError("version_not_restorable")
        doc = self.get(v["document_id"])
        with self.db.transaction():
            self._switch_active(doc, version_id)
        self.audit.log("revision_restore", "document_versions", version_id,
                       {"document": doc["title"], "version_no": v["version_no"]})

    def discard_revision(self, version_id: int) -> None:
        """Отказ от редакции на проверке (до активации). Редакция удаляется,
        если по ней не проводилось тестирование."""
        v = self.version(version_id)
        if v is None or v["status"] not in (VersionStatus.REVIEW, VersionStatus.DRAFT):
            raise DocumentError("version_not_discardable")
        if self.db.scalar("SELECT COUNT(*) FROM test_questions WHERE version_id = ?", (version_id,)):
            raise DocumentError("doc_used_in_tests")
        with self.db.transaction():
            self.db.execute("DELETE FROM questions WHERE version_id = ?", (version_id,))
            self.db.execute("DELETE FROM document_changes WHERE new_version_id = ?", (version_id,))
            self.db.execute("DELETE FROM requirements WHERE version_id = ?", (version_id,))
            self.db.execute("DELETE FROM document_sections WHERE version_id = ?", (version_id,))
            self.db.execute("DELETE FROM document_versions WHERE id = ?", (version_id,))
            self.db.execute("UPDATE documents SET status = 'active', updated_at = ? WHERE id = ? AND status = 'revision_review'",
                            (now_iso(), v["document_id"]))
        Path(v["stored_path"]).unlink(missing_ok=True)
        self.audit.log("revision_discard", "document_versions", version_id)

    def set_analysis_state(self, version_id: int, state: str) -> None:
        self.db.execute("UPDATE document_versions SET analysis_state = ? WHERE id = ?", (state, version_id))

    def changed_since(self, document_id: int, version_id: int) -> bool:
        """Есть ли изменения требований между редакцией version_id и действующей."""
        doc = self.get(document_id)
        if doc is None or doc["active_version_id"] == version_id:
            return False
        newer = self.db.query("SELECT id FROM document_versions WHERE document_id = ? AND version_no > "
                              "(SELECT version_no FROM document_versions WHERE id = ?) AND status IN ('active','superseded')",
                              (document_id, version_id))
        for r in newer:
            if self.db.scalar("SELECT COUNT(*) FROM document_changes WHERE new_version_id = ? AND change_type "
                              "IN ('added','modified','removed','manual')", (r["id"],)):
                return True
        return False
