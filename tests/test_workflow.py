"""Сквозной сценарий: документ → вопросы → утверждение → тест → результат →
новая редакция → актуализация → отчёты → резервная копия."""
import json
import random
import sqlite3

import pytest

from ibtest.models.common import QStatus
from ibtest.services.documents import DocumentError
from ibtest.services.test_engine.engine import TestBuildError, TestEngine


def _import(ctx, path, title):
    parsed = ctx.documents.parse_file(path)
    return ctx.documents.import_document(path, parsed, title)


def _generate(ctx, fake_llm, doc_id, section_ids=None):
    doc = ctx.documents.get(doc_id)
    gen = ctx.make_generator(backend=fake_llm)
    return gen.generate_for_version(doc["active_version_id"], section_ids)


def _approve_all(ctx, version_id):
    ids = [q["id"] for q in ctx.questions.list(version_id=version_id, status=QStatus.REVIEW)]
    ctx.questions.set_status(ids, QStatus.APPROVED)
    return len(ids)


def _profile(ctx, doc_id, n=10, pass_score=80, policy="block"):
    return ctx.profiles.save(None, "Основной", n, 30, pass_score, None, policy, [(doc_id, n)], True)


def test_admin_auth(ctx):
    from ibtest.services.security.auth import AuthError
    with pytest.raises(AuthError):
        ctx.auth.create_admin("admin", "short")
    ctx.auth.create_admin("admin", "Str0ngPassw0rd")
    row = ctx.db.one("SELECT password_hash FROM admin_users")
    assert row["password_hash"].startswith("scrypt$") and "Str0ng" not in row["password_hash"]
    with pytest.raises(AuthError):
        ctx.auth.login("admin", "wrong-pass1A")
    s = ctx.auth.login("admin", "Str0ngPassw0rd")
    assert s.username == "admin"
    for _ in range(5):
        with pytest.raises(AuthError):
            ctx.auth.login("admin", "bad")
    with pytest.raises(AuthError) as e:
        ctx.auth.login("admin", "Str0ngPassw0rd")
    assert e.value.key == "login_locked"
    with pytest.raises(sqlite3.DatabaseError):
        ctx.db.execute("DELETE FROM audit_logs")


def test_generation_pipeline(ctx, files, fake_llm):
    doc_id = _import(ctx, files["docx_ru"], "Правила ИБ")
    doc = ctx.documents.get(doc_id)
    assert doc["language"] == "ru" and doc["doc_number"] == "45-п"
    stats = _generate(ctx, fake_llm, doc_id)
    assert stats.saved >= 15
    assert stats.requirements >= 9
    qs = ctx.questions.list(document_id=doc_id)
    assert all(q["status"] == QStatus.REVIEW for q in qs), "сгенерированные вопросы не утверждены автоматически"
    q = ctx.questions.get(qs[0]["id"])
    assert q["section_number"] and q["source_text"] and q["requirement_id"]
    assert ctx.questions.usable_count(doc_id) == 0
    # Повторная генерация не создаёт дублей
    again = _generate(ctx, fake_llm, doc_id)
    assert again.saved == 0 and again.rejected_duplicate > 0


def test_grounding_rejects_invented(ctx, files):
    from tests.conftest import FakeLLM
    doc_id = _import(ctx, files["docx_ru"], "Правила ИБ")
    stats = _generate(ctx, FakeLLM(bad_quote=True), doc_id)
    assert stats.saved == 0 and stats.rejected_grounding > 0


def test_kazakh_generation(ctx, files, fake_llm):
    doc_id = _import(ctx, files["pdf_kk"], "Ақпараттық қауіпсіздік қағидалары")
    assert ctx.documents.get(doc_id)["language"] == "kk"
    stats = _generate(ctx, fake_llm, doc_id)
    assert stats.saved > 0
    qs = ctx.questions.list(document_id=doc_id)
    assert all(q["language"] == "kk" for q in qs)
    tf = [q for q in qs if q["qtype"] == "truefalse"]
    opts = [o["text"] for o in ctx.questions.options(tf[0]["id"])]
    assert opts == ["Дұрыс", "Бұрыс"]
    assert any("құпиясөз" in q["text"].lower() or "Құпиясөз" in q["text"] for q in qs)
    # Промпт для казахского документа — на казахском, без перевода
    assert any("ҮЗІНДІ" in c for c in fake_llm.calls)


def test_full_testing_cycle(ctx, files, fake_llm):
    doc_id = _import(ctx, files["docx_ru"], "Правила ИБ")
    _generate(ctx, fake_llm, doc_id)
    approved = _approve_all(ctx, ctx.documents.get(doc_id)["active_version_id"])
    assert approved >= 15
    pid = _profile(ctx, doc_id, n=12)
    emp = ctx.employees.find_or_create("иванов  иван иванович", "Бухгалтерия", "Бухгалтер")
    assert ctx.employees.get(emp)["full_name"] == "Иванов Иван Иванович"
    assert ctx.employees.find_or_create("Иванов Иван Иванович", "бухгалтерия") == emp

    engine = TestEngine(ctx.db, ctx.audit, random.Random(1))
    sid = engine.build(pid, emp)
    qs = engine.questions(sid)
    assert len(qs) == 12 and len({q.text for q in qs}) == 12
    # Правильные ответы не раскрываются до завершения
    with pytest.raises(TestBuildError):
        engine.review(sid)
    for i, q in enumerate(qs):
        right = [k for k, o in enumerate(q.options) if o["correct"]]
        engine.answer(sid, q.id, right if i < 10 else [k for k in range(len(q.options)) if k not in right][:1])
    res = engine.finish(sid)
    assert res["correct"] == 10 and res["wrong"] == 2 and res["percent"] == pytest.approx(83.3, 0.1)
    assert res["passed"] == 1
    assert engine.verify_integrity(sid)
    # Результат неизменяем
    with pytest.raises(sqlite3.DatabaseError):
        ctx.db.execute("UPDATE test_results SET percent = 100 WHERE session_id = ?", (sid,))
    with pytest.raises(sqlite3.DatabaseError):
        ctx.db.execute("UPDATE employee_answers SET selected_json = '[0]'")
    with pytest.raises(sqlite3.DatabaseError):
        ctx.db.execute("DELETE FROM test_sessions WHERE id = ?", (sid,))
    with pytest.raises(TestBuildError):
        engine.answer(sid, qs[0].id, [0])
    # Повторная попытка — отдельная запись, другой набор
    sid2 = engine.build(pid, emp)
    engine.finish(sid2)
    assert ctx.db.scalar("SELECT COUNT(*) FROM test_results") == 2
    h = ctx.db.query("SELECT question_set_hash FROM test_sessions")
    assert h[0][0] != h[1][0]
    card = ctx.results.employee_card(emp)
    assert len(card["attempts"]) == 2 and card["attempts"][1]["passed"] == 0
    rows = ctx.results.list(__import__("ibtest.services.analytics.results", fromlist=["ResultFilter"]).ResultFilter(search="иванов"))
    assert len(rows) == 2 and "ред. 1" in rows[0]["documents"]


def test_random_selection_and_shuffle(ctx, files, fake_llm):
    doc_id = _import(ctx, files["docx_ru"], "Правила ИБ")
    _generate(ctx, fake_llm, doc_id)
    _approve_all(ctx, ctx.documents.get(doc_id)["active_version_id"])
    pool = ctx.questions.usable_count(doc_id)
    n = min(30, pool - 2)
    pid = _profile(ctx, doc_id, n=n)
    emp = ctx.employees.find_or_create("Петров Пётр", "ИТ")
    engine = TestEngine(ctx.db, ctx.audit)
    sets, first_correct = set(), []
    for _ in range(6):
        sid = engine.build(pid, emp)
        qs = engine.questions(sid)
        assert len(qs) == n
        sets.add(tuple(q.text for q in qs))
        first_correct += [next(i for i, o in enumerate(q.options) if o["correct"]) for q in qs if q.qtype == "single"]
        engine.finish(sid)
    assert len(sets) == 6
    assert len(set(first_correct)) > 1, "варианты ответов перемешиваются"
    # Балансировка: в тесте представлены все разделы
    groups = {r["top_group"] for r in ctx.db.query(
        "SELECT DISTINCT s.top_group FROM test_questions tq JOIN questions q ON q.id = tq.question_id "
        "JOIN document_sections s ON s.id = q.section_id WHERE tq.session_id = ?", (sid,))}
    assert len(groups) >= 4


def test_insufficient_questions(ctx, files, fake_llm):
    doc_id = _import(ctx, files["docx_ru"], "Правила ИБ")
    _generate(ctx, fake_llm, doc_id)
    _approve_all(ctx, ctx.documents.get(doc_id)["active_version_id"])
    pid = _profile(ctx, doc_id, n=100)
    emp = ctx.employees.find_or_create("Сидоров Сидор", "ИТ")
    with pytest.raises(TestBuildError) as e:
        ctx.tests.build(pid, emp)
    assert e.value.key == "not_enough_questions"
    pid2 = ctx.profiles.save(None, "Короткий", 100, 30, 80, None, "shorten", [(doc_id, 100)], False)
    sid = ctx.tests.build(pid2, emp)
    assert len(ctx.tests.questions(sid)) == ctx.questions.usable_count(doc_id)


def test_revision_update(ctx, files, fake_llm):
    doc_id = _import(ctx, files["docx_ru"], "Правила ИБ")
    _generate(ctx, fake_llm, doc_id)
    v1 = ctx.documents.get(doc_id)["active_version_id"]
    _approve_all(ctx, v1)
    pid = _profile(ctx, doc_id, n=10)
    emp = ctx.employees.find_or_create("Иванов Иван", "Бухгалтерия")
    sid = ctx.tests.build(pid, emp)
    for q in ctx.tests.questions(sid):
        ctx.tests.answer(sid, q.id, [i for i, o in enumerate(q.options) if o["correct"]])
    before = ctx.tests.finish(sid)
    snapshot = ctx.db.query("SELECT text, options_json, version_id FROM test_questions WHERE session_id = ?", (sid,))

    # Идентичная редакция отклоняется
    with pytest.raises(DocumentError):
        ctx.documents.add_revision(doc_id, files["txt_ru"], ctx.documents.parse_file(files["txt_ru"]))

    rev = ctx.documents.add_revision(doc_id, files["docx_ru_v2"], ctx.documents.parse_file(files["docx_ru_v2"]))
    s = rev.summary
    assert s["added"] == 1 and s["removed"] == 1 and s["modified"] == 1
    assert s["unchanged"] >= 10
    ch = ctx.documents.changes(rev.version_id)
    mod = next(c for c in ch if c["change_type"] == "modified")
    assert "12 символов" in mod["old_text"] and "14 символов" in mod["new_text"]
    added = next(c for c in ch if c["change_type"] == "added")
    assert added["new_number"] == "3.4"
    removed = next(c for c in ch if c["change_type"] == "removed")
    assert removed["old_number"] == "4.2"
    assert ctx.documents.get(doc_id)["status"] == "revision_review"

    # Вопросы: неизменённые — перенесены утверждёнными, изменённые — на повторную проверку
    assert rev.carried_approved > 0 and rev.carried_review > 0
    v2_q = ctx.questions.list(version_id=rev.version_id)
    mod_q = [q for q in v2_q if q["section_number"] == "2.1"]
    assert mod_q and all(q["status"] == "review" for q in mod_q)
    assert not [q for q in v2_q if q["section_number"] == "4.2"], "вопросы по удалённому пункту не переносятся"
    # До активации тест строится по редакции 1
    sid_mid = ctx.tests.build(pid, emp)
    assert {r[0] for r in ctx.db.query("SELECT DISTINCT version_id FROM test_questions WHERE session_id=?", (sid_mid,))} == {v1}
    ctx.tests.finish(sid_mid)

    # Генерация по новым и изменённым пунктам
    gen = ctx.make_generator(backend=fake_llm).generate_for_version(rev.version_id, rev.sections_to_generate)
    assert gen.saved > 0
    new_q = ctx.questions.list(version_id=rev.version_id, status="review")
    assert any(q["section_number"] == "3.4" for q in new_q)
    ctx.questions.set_status([q["id"] for q in new_q], "approved")
    ctx.documents.activate_version(rev.version_id)
    doc = ctx.documents.get(doc_id)
    assert doc["active_version_id"] == rev.version_id and doc["status"] == "active"
    # Устаревшие вопросы не попадают в тест
    assert ctx.db.scalar("SELECT COUNT(*) FROM questions WHERE version_id = ? AND status = 'approved'", (v1,)) == 0
    sid2 = ctx.tests.build(pid, emp)
    vids = {r[0] for r in ctx.db.query("SELECT DISTINCT version_id FROM test_questions WHERE session_id=?", (sid2,))}
    assert vids == {rev.version_id}
    texts = [r[0] for r in ctx.db.query("SELECT text FROM test_questions WHERE session_id = ?", (sid2,))]
    assert not any("4.2" in t for t in texts)
    ctx.tests.finish(sid2)
    # История прежнего результата не изменилась
    assert ctx.tests.result(sid)["percent"] == before["percent"]
    assert ctx.db.query("SELECT text, options_json, version_id FROM test_questions WHERE session_id = ?", (sid,)) == snapshot
    # Контроль: сотрудник сдавал прежнюю редакцию — требуется повторное тестирование
    ctl = ctx.results.control(doc_id)
    row = next(r for r in ctl if r["employee_id"] == emp)
    assert row["status"] in ("retest", "failed")
    # Восстановление предыдущей редакции
    ctx.documents.restore_version(v1)
    assert ctx.documents.get(doc_id)["active_version_id"] == v1
    assert ctx.questions.usable_count(doc_id) > 0
    assert ctx.db.scalar("SELECT COUNT(*) FROM document_versions WHERE document_id = ?", (doc_id,)) == 2


def test_document_cannot_be_deleted_after_tests(ctx, files, fake_llm):
    doc_id = _import(ctx, files["docx_ru"], "Правила ИБ")
    _generate(ctx, fake_llm, doc_id)
    _approve_all(ctx, ctx.documents.get(doc_id)["active_version_id"])
    pid = _profile(ctx, doc_id, n=5)
    emp = ctx.employees.find_or_create("Иванов Иван", "Бухгалтерия")
    ctx.tests.finish(ctx.tests.build(pid, emp))
    with pytest.raises(DocumentError) as e:
        ctx.documents.delete_document(doc_id)
    assert e.value.key == "doc_used_in_tests"
    ctx.documents.set_status(doc_id, "revoked")
    assert ctx.results.list(__import__("ibtest.services.analytics.results", fromlist=["x"]).ResultFilter())
    with pytest.raises(TestBuildError):
        ctx.tests.build(pid, emp)


def test_question_edit_and_validation(ctx, files, fake_llm):
    from ibtest.models.common import OptionData, QuestionData
    from ibtest.services.questions import QuestionError
    doc_id = _import(ctx, files["docx_ru"], "Правила ИБ")
    vid = ctx.documents.get(doc_id)["active_version_id"]
    bad = QuestionData("single", "Сколько символов должен содержать пароль?",
                       [OptionData("12", True), OptionData("14", True), OptionData("8", False), OptionData("6", False)])
    with pytest.raises(QuestionError) as e:
        ctx.questions.create(bad, doc_id, vid)
    assert e.value.key == "q_need_one_correct"
    good = QuestionData("multiple", "Что должен содержать пароль?",
                        [OptionData("Прописные буквы", True), OptionData("Цифры", True),
                         OptionData("Имя работника", False), OptionData("Дату рождения", False)])
    qid = ctx.questions.create(good, doc_id, vid, status="draft", origin="manual")
    ctx.questions.set_status([qid], "approved")
    good.text = "Какие символы должен содержать пароль?"
    ctx.questions.update(qid, good)
    assert ctx.questions.get(qid)["status"] == "review", "правка утверждённого вопроса требует повторного утверждения"
    hist = [a["action"] for a in ctx.questions.approvals(qid)]
    assert hist == ["create", "approve", "edit"]


def test_reports_and_backup(ctx, files, fake_llm, tmp_path):
    from ibtest.services.analytics.results import ResultFilter
    from ibtest.services.report_generator.reports import Report, export_excel, export_pdf
    doc_id = _import(ctx, files["docx_kk"], "Ақпараттық қауіпсіздік қағидалары")
    _generate(ctx, fake_llm, doc_id)
    _approve_all(ctx, ctx.documents.get(doc_id)["active_version_id"])
    n = ctx.questions.usable_count(doc_id)
    pid = _profile(ctx, doc_id, n=n)
    emp = ctx.employees.find_or_create("Әбілқасымов Нұрлан Қайратұлы", "Қаржы бөлімі", "Маман")
    ctx.tests.finish(ctx.tests.build(pid, emp))
    f = ResultFilter()
    rep = Report("Есеп", summary=ctx.results.summary(f), results=ctx.results.list(f),
                 by_department=ctx.results.by_department(f), by_document=ctx.results.by_document(f),
                 by_month=ctx.results.by_month(f))
    xlsx = export_excel(rep, tmp_path / "r.xlsx")
    from openpyxl import load_workbook
    wb = load_workbook(xlsx)
    vals = [c.value for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value]
    assert "Әбілқасымов Нұрлан Қайратұлы" in vals and "Қаржы бөлімі" in vals
    pdf = export_pdf(rep, tmp_path / "r.pdf")
    import pypdfium2 as pdfium
    p = pdfium.PdfDocument(str(pdf))
    text = "".join(p[i].get_textpage().get_text_range() for i in range(len(p)))
    assert "Әбілқасымов" in text and "Қаржы бөлімі" in text

    # Резервная копия и восстановление
    before = ctx.db.scalar("SELECT COUNT(*) FROM test_results")
    bk = ctx.backup.create("manual", password="Backup-Pass1")
    chk = ctx.backup.verify(bk, "Backup-Pass1")
    assert chk.ok and chk.tests == before
    assert not ctx.backup.verify(bk, "wrong").ok
    ctx.tests.finish(ctx.tests.build(pid, emp))
    assert ctx.db.scalar("SELECT COUNT(*) FROM test_results") == before + 1
    safety = ctx.backup.restore(bk, "Backup-Pass1")
    assert safety.exists()
    assert ctx.db.scalar("SELECT COUNT(*) FROM test_results") == before
    assert ctx.db.integrity_check()[0]
    # Страховочная копия содержит данные до восстановления
    assert ctx.backup.verify(safety).tests == before + 1
    # Оригинал документа восстановлен
    from pathlib import Path
    stored = ctx.db.scalar("SELECT stored_path FROM document_versions LIMIT 1")
    assert Path(stored).exists()


def test_secret_store_and_auto_backup(ctx):
    ctx.backup.set_stored_password("Auto-Pass1")
    assert ctx.backup.stored_password() == "Auto-Pass1"
    assert ctx.backup.auto_due()
    p = ctx.backup.run_auto_if_due()
    assert p and ctx.backup.verify(p, "Auto-Pass1").ok
    assert not ctx.backup.auto_due()


def test_migrations_idempotent(ctx):
    from ibtest.database import migrations
    assert migrations.migrate(ctx.db.conn) == migrations.latest_version()
    ctx.db.execute(f"PRAGMA user_version = {migrations.latest_version() + 1}")
    with pytest.raises(RuntimeError):
        migrations.migrate(ctx.db.conn)
    ctx.db.execute(f"PRAGMA user_version = {migrations.latest_version()}")
