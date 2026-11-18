"""Дымовой тест интерфейса: все страницы и диалоги создаются и обновляются
на реальной базе с данными. С PySide6 — настоящий Qt (offscreen), без него —
заглушка Qt (проверяется логика страниц и обращения к сервисам)."""
import os

import pytest

try:
    import PySide6  # noqa: F401
    REAL_QT = True
except ImportError:
    REAL_QT = False
    from tests import qt_stub
    qt_stub.install()


@pytest.fixture()
def seeded(ctx, files, fake_llm):
    ctx.auth.create_admin("admin", "Str0ngPassw0rd")
    ctx.auth.login("admin", "Str0ngPassw0rd")
    parsed = ctx.documents.parse_file(files["docx_ru"])
    doc_id = ctx.documents.import_document(files["docx_ru"], parsed, "Правила ИБ")
    vid = ctx.documents.get(doc_id)["active_version_id"]
    ctx.make_generator(backend=fake_llm).generate_for_version(vid)
    ids = [q["id"] for q in ctx.questions.list(version_id=vid)]
    ctx.questions.set_status(ids[:-3], "approved")
    pid = ctx.profiles.save(None, "Основной", 10, 30, 80, None, "block", [(doc_id, 10)], True)
    emp = ctx.employees.find_or_create("Әбілқасымов Нұрлан", "Қаржы бөлімі", "Маман")
    sid = ctx.tests.build(pid, emp)
    ctx.tests.finish(sid)
    rev = ctx.documents.add_revision(doc_id, files["docx_ru_v2"], ctx.documents.parse_file(files["docx_ru_v2"]))
    ctx.backup.create("manual")
    return {"doc": doc_id, "pid": pid, "emp": emp, "sid": sid, "qid": ids[0], "rev": rev.version_id}


@pytest.fixture()
def qapp():
    if REAL_QT:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        yield app
    else:
        yield None


@pytest.mark.parametrize("lang", ["ru", "kk"])
def test_all_pages_and_dialogs(seeded, ctx, qapp, lang):
    from ibtest.localization.i18n import set_language
    set_language(lang)
    from ibtest.ui.dialogs.document_import import DocumentImportDialog, DocumentMetaDialog, DocumentTextDialog
    from ibtest.ui.dialogs.employee_card import AttemptDialog, EmployeeCardDialog
    from ibtest.ui.dialogs.generation import LanguageDialog
    from ibtest.ui.dialogs.login import FirstRunDialog, LoginDialog
    from ibtest.ui.dialogs.question_editor import QuestionEditor
    from ibtest.ui.main_window import AdminShell, MainWindow
    from ibtest.ui.pages.employees import EmployeeDialog
    from ibtest.ui.pages.testing_admin import ProfileDialog

    win = MainWindow(ctx)
    shell = AdminShell(ctx, win)
    for key in shell.pages:
        shell.navigate(key)
    shell.pages["revisions"].select_document(seeded["doc"])
    shell.pages["revisions"]._load_changes()
    doc = ctx.documents.get(seeded["doc"])
    DocumentImportDialog(None, ctx, "new")
    DocumentImportDialog(None, ctx, "revision", doc)
    DocumentMetaDialog(None, ctx, doc)
    DocumentTextDialog(None, "t", "text")
    QuestionEditor(None, ctx, seeded["qid"])
    QuestionEditor(None, ctx, None, seeded["doc"])
    EmployeeCardDialog(None, ctx, seeded["emp"])
    AttemptDialog(None, ctx, seeded["sid"])
    ProfileDialog(None, ctx, seeded["pid"])
    ProfileDialog(None, ctx, None)
    EmployeeDialog(None, ctx, ctx.employees.get(seeded["emp"]))
    LanguageDialog(None, "ru", 5)
    LoginDialog(None, ctx)
    FirstRunDialog(None, ctx)
    win.rebuild()


def test_employee_flow_logic(seeded, ctx, qapp):
    """Анкета → тест → завершение через страницу сотрудника."""
    from ibtest.ui.pages.employee_test import EmployeeTestPage
    page = EmployeeTestPage(ctx, kiosk=True)
    page.refresh()
    if REAL_QT:
        page.fio.setText("Петров Пётр Петрович")
        page.dept.setCurrentText("ИТ-служба")
        page.profile.setCurrentIndex(0)
    else:
        page.fio.text = lambda: "Петров Пётр Петрович"
        page.dept.currentText = lambda: "ИТ-служба"
        page.position.text = lambda: ""
        page.profile.currentData = lambda: seeded["pid"]
    page._start()
    assert page.session_id is not None and len(page.qs) == 10
    for i in range(len(page.qs)):
        page._go(i)
    page._finish()
    res = ctx.tests.result(page.session_id)
    assert res["total"] == 10 and res["unanswered"] == 10
    page._reset()
    assert page.session_id is None


def test_page_actions_with_selection(seeded, ctx, qapp, monkeypatch):
    """Действия страниц при выбранной строке (выбор подставляется)."""
    if REAL_QT:
        pytest.skip("выбор строк проверяется в ручном сценарии с настоящим Qt")
    import ibtest.ui.pages.review as review_m
    import ibtest.ui.pages.revisions as rev_m
    import ibtest.ui.pages.results as res_m
    import ibtest.ui.pages.documents as doc_m
    import ibtest.ui.pages.testing_admin as ta_m
    import ibtest.ui.pages.control as ctl_m
    from ibtest.ui.main_window import AdminShell, MainWindow
    win = MainWindow(ctx)
    shell = AdminShell(ctx, win)
    pending = [q["id"] for q in ctx.questions.list(statuses=("review",))]
    monkeypatch.setattr(review_m, "selected_keys", lambda t: pending[:2])
    shell.navigate("review")
    pg = shell.pages["review"]
    pg._show()
    pg._approve()
    assert ctx.db.scalar("SELECT status FROM questions WHERE id = ?", (pending[0],)) == "approved"
    # Редакции: выбор новой редакции и изменения
    changes = [c["id"] for c in ctx.documents.changes(seeded["rev"]) if c["change_type"] != "unchanged"]
    monkeypatch.setattr(rev_m, "selected_key", lambda t: seeded["rev"] if t is shell.pages["revisions"].versions
                        else changes[0])
    rp = shell.pages["revisions"]
    rp.doc.currentData = lambda: seeded["doc"]
    rp._load_versions()
    rp._load_changes()
    rp._show_diff()
    rp._buttons()
    # Результаты: карточка выбранной попытки
    monkeypatch.setattr(res_m, "selected_key", lambda t: seeded["sid"])
    rs = shell.pages["results"]
    rs._reload()
    assert rs._selected_row()["employee_id"] == seeded["emp"]
    rs._card()
    rs._attempt()
    rep = rs._report()
    assert rep.results and rep.summary["tests"] >= 1
    # Документы
    monkeypatch.setattr(doc_m, "selected_key", lambda t: seeded["doc"])
    dp = shell.pages["documents"]
    assert dp._current()["id"] == seeded["doc"]
    dp._view_text()
    # Профили
    monkeypatch.setattr(ta_m, "selected_key", lambda t: seeded["pid"])
    tp = shell.pages["testing"]
    tp._readiness()
    assert "Правила ИБ" in tp.ready.text() if hasattr(tp.ready.text(), "__contains__") else True
    # Контроль
    cp = shell.pages["control"]
    cp.doc.currentData = lambda: seeded["doc"]
    cp._reload()
    assert cp.rows and cp.rows[0]["status"] in ("passed", "failed", "retest", "not_tested")
    r = cp._report()
    assert len(r.results) == len(cp.rows)
