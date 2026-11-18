"""Миграции схемы SQLite.

Версия схемы хранится в PRAGMA user_version. Каждая миграция — список SQL
выражений, применяемых в одной транзакции. Новые миграции только добавляются
в конец списка; применённые миграции никогда не изменяются.
"""
from __future__ import annotations

import sqlite3

MIGRATIONS: list[str] = []

# ---------------------------------------------------------------- v1
MIGRATIONS.append(r"""
CREATE TABLE application_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

CREATE TABLE admin_users (
    id                   INTEGER PRIMARY KEY,
    username             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name            TEXT,
    password_hash        TEXT NOT NULL,
    role                 TEXT NOT NULL DEFAULT 'admin' CHECK (role IN ('admin','auditor')),
    is_active            INTEGER NOT NULL DEFAULT 1,
    failed_attempts      INTEGER NOT NULL DEFAULT 0,
    locked_until         TEXT,
    last_login_at        TEXT,
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

CREATE TABLE audit_logs (
    id          INTEGER PRIMARY KEY,
    admin_id    INTEGER REFERENCES admin_users(id) ON DELETE SET NULL,
    username    TEXT,
    action      TEXT NOT NULL,
    entity      TEXT,
    entity_id   TEXT,
    details     TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);
CREATE INDEX ix_audit_created ON audit_logs(created_at);
CREATE TRIGGER trg_audit_no_update BEFORE UPDATE ON audit_logs
BEGIN SELECT RAISE(ABORT, 'Журнал действий не может изменяться'); END;
CREATE TRIGGER trg_audit_no_delete BEFORE DELETE ON audit_logs
BEGIN SELECT RAISE(ABORT, 'Записи журнала действий не удаляются'); END;

CREATE TABLE departments (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    name_norm   TEXT NOT NULL UNIQUE,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

CREATE TABLE employees (
    id              INTEGER PRIMARY KEY,
    uid             TEXT NOT NULL UNIQUE,
    full_name       TEXT NOT NULL,
    full_name_norm  TEXT NOT NULL,
    department_id   INTEGER NOT NULL REFERENCES departments(id) ON DELETE RESTRICT,
    position        TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
    UNIQUE (full_name_norm, department_id)
);
CREATE INDEX ix_employees_dept ON employees(department_id);

CREATE TABLE documents (
    id                 INTEGER PRIMARY KEY,
    uid                TEXT NOT NULL UNIQUE,
    title              TEXT NOT NULL,
    doc_number         TEXT,
    doc_date           TEXT,
    effective_date     TEXT,
    language           TEXT NOT NULL DEFAULT 'ru' CHECK (language IN ('ru','kk','other')),
    status             TEXT NOT NULL DEFAULT 'active'
                       CHECK (status IN ('active','revision_review','pending_update','archived','revoked')),
    active_version_id  INTEGER REFERENCES document_versions(id) ON DELETE RESTRICT,
    is_mandatory       INTEGER NOT NULL DEFAULT 1,
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
    updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

CREATE TABLE document_versions (
    id              INTEGER PRIMARY KEY,
    uid             TEXT NOT NULL UNIQUE,
    document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE RESTRICT,
    version_no      INTEGER NOT NULL,
    file_name       TEXT NOT NULL,
    stored_path     TEXT NOT NULL,
    file_sha256     TEXT NOT NULL,
    text_sha256     TEXT NOT NULL,
    raw_text        TEXT NOT NULL,
    language        TEXT NOT NULL,
    doc_number      TEXT,
    doc_date        TEXT,
    effective_date  TEXT,
    ocr_used        INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft','review','active','superseded')),
    analysis_state  TEXT NOT NULL DEFAULT 'not_started'
                    CHECK (analysis_state IN ('not_started','running','done','failed','partial')),
    note            TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
    activated_at    TEXT,
    UNIQUE (document_id, version_no)
);
CREATE INDEX ix_versions_text_hash ON document_versions(text_sha256);
CREATE INDEX ix_versions_file_hash ON document_versions(file_sha256);

CREATE TABLE document_sections (
    id            INTEGER PRIMARY KEY,
    version_id    INTEGER NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    order_index   INTEGER NOT NULL,
    number        TEXT,
    heading       TEXT,
    text          TEXT NOT NULL,
    norm_hash     TEXT NOT NULL,
    top_group     TEXT
);
CREATE INDEX ix_sections_version ON document_sections(version_id);

CREATE TABLE document_changes (
    id               INTEGER PRIMARY KEY,
    new_version_id   INTEGER NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    old_version_id   INTEGER NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    old_section_id   INTEGER REFERENCES document_sections(id) ON DELETE SET NULL,
    new_section_id   INTEGER REFERENCES document_sections(id) ON DELETE SET NULL,
    change_type      TEXT NOT NULL CHECK (change_type IN ('added','modified','removed','unchanged','manual')),
    similarity       REAL,
    resolved         INTEGER NOT NULL DEFAULT 0,
    resolution       TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);
CREATE INDEX ix_changes_new ON document_changes(new_version_id);

CREATE TABLE requirements (
    id           INTEGER PRIMARY KEY,
    uid          TEXT NOT NULL UNIQUE,
    version_id   INTEGER NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    section_id   INTEGER REFERENCES document_sections(id) ON DELETE SET NULL,
    category     TEXT,
    text         TEXT NOT NULL,
    source_text  TEXT,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);
CREATE INDEX ix_requirements_version ON requirements(version_id);

CREATE TABLE questions (
    id                  INTEGER PRIMARY KEY,
    uid                 TEXT NOT NULL UNIQUE,
    document_id         INTEGER NOT NULL REFERENCES documents(id) ON DELETE RESTRICT,
    version_id          INTEGER NOT NULL REFERENCES document_versions(id) ON DELETE RESTRICT,
    section_id          INTEGER REFERENCES document_sections(id) ON DELETE SET NULL,
    requirement_id      INTEGER REFERENCES requirements(id) ON DELETE SET NULL,
    parent_question_id  INTEGER REFERENCES questions(id) ON DELETE SET NULL,
    qtype               TEXT NOT NULL CHECK (qtype IN ('single','multiple','truefalse','situational')),
    text                TEXT NOT NULL,
    explanation         TEXT,
    section_number      TEXT,
    source_text         TEXT,
    language            TEXT NOT NULL CHECK (language IN ('ru','kk')),
    difficulty          TEXT NOT NULL DEFAULT 'medium' CHECK (difficulty IN ('easy','medium','hard')),
    status              TEXT NOT NULL DEFAULT 'review'
                        CHECK (status IN ('draft','review','approved','rejected','obsolete')),
    previous_status     TEXT,
    origin              TEXT NOT NULL DEFAULT 'ai' CHECK (origin IN ('ai','manual','carried')),
    review_note         TEXT,
    norm_text           TEXT NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);
CREATE INDEX ix_questions_version_status ON questions(version_id, status);
CREATE INDEX ix_questions_document ON questions(document_id);

CREATE TABLE question_options (
    id           INTEGER PRIMARY KEY,
    question_id  INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    order_index  INTEGER NOT NULL,
    text         TEXT NOT NULL,
    is_correct   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX ix_options_question ON question_options(question_id);

CREATE TABLE question_approvals (
    id           INTEGER PRIMARY KEY,
    question_id  INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    admin_id     INTEGER REFERENCES admin_users(id) ON DELETE SET NULL,
    action       TEXT NOT NULL,
    from_status  TEXT,
    to_status    TEXT,
    comment      TEXT,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

CREATE TABLE test_profiles (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL UNIQUE,
    question_count   INTEGER NOT NULL DEFAULT 30 CHECK (question_count > 0),
    time_limit_min   INTEGER NOT NULL DEFAULT 40 CHECK (time_limit_min >= 0),
    pass_score       INTEGER NOT NULL DEFAULT 80 CHECK (pass_score BETWEEN 1 AND 100),
    language         TEXT CHECK (language IN ('ru','kk') OR language IS NULL),
    insufficient_policy TEXT NOT NULL DEFAULT 'block' CHECK (insufficient_policy IN ('block','shorten')),
    is_active        INTEGER NOT NULL DEFAULT 1,
    is_default       INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

CREATE TABLE test_profile_documents (
    profile_id      INTEGER NOT NULL REFERENCES test_profiles(id) ON DELETE CASCADE,
    document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    question_count  INTEGER NOT NULL CHECK (question_count > 0),
    PRIMARY KEY (profile_id, document_id)
);

CREATE TABLE test_sessions (
    id                  INTEGER PRIMARY KEY,
    uid                 TEXT NOT NULL UNIQUE,
    employee_id         INTEGER NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
    profile_id          INTEGER REFERENCES test_profiles(id) ON DELETE SET NULL,
    profile_name        TEXT,
    employee_name       TEXT NOT NULL,
    department_name     TEXT NOT NULL,
    position            TEXT,
    language            TEXT NOT NULL,
    question_count      INTEGER NOT NULL,
    pass_score          INTEGER NOT NULL,
    time_limit_min      INTEGER NOT NULL,
    question_set_hash   TEXT NOT NULL,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    duration_sec        INTEGER,
    status              TEXT NOT NULL DEFAULT 'in_progress'
                        CHECK (status IN ('in_progress','finished','expired','aborted'))
);
CREATE INDEX ix_sessions_employee ON test_sessions(employee_id);
CREATE INDEX ix_sessions_started ON test_sessions(started_at);

CREATE TABLE test_questions (
    id                    INTEGER PRIMARY KEY,
    session_id            INTEGER NOT NULL REFERENCES test_sessions(id) ON DELETE RESTRICT,
    order_index           INTEGER NOT NULL,
    question_id           INTEGER REFERENCES questions(id) ON DELETE SET NULL,
    question_uid          TEXT NOT NULL,
    document_id           INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    version_id            INTEGER REFERENCES document_versions(id) ON DELETE SET NULL,
    document_title        TEXT NOT NULL,
    version_no            INTEGER NOT NULL,
    section_number        TEXT,
    qtype                 TEXT NOT NULL,
    difficulty            TEXT,
    text                  TEXT NOT NULL,
    options_json          TEXT NOT NULL,
    explanation           TEXT,
    UNIQUE (session_id, order_index)
);
CREATE INDEX ix_tq_session ON test_questions(session_id);
CREATE INDEX ix_tq_document ON test_questions(document_id);

CREATE TABLE employee_answers (
    id                INTEGER PRIMARY KEY,
    test_question_id  INTEGER NOT NULL UNIQUE REFERENCES test_questions(id) ON DELETE RESTRICT,
    selected_json     TEXT NOT NULL,
    is_correct        INTEGER,
    answered_at       TEXT NOT NULL
);

CREATE TABLE test_results (
    id             INTEGER PRIMARY KEY,
    session_id     INTEGER NOT NULL UNIQUE REFERENCES test_sessions(id) ON DELETE RESTRICT,
    total          INTEGER NOT NULL,
    correct        INTEGER NOT NULL,
    wrong          INTEGER NOT NULL,
    unanswered     INTEGER NOT NULL,
    percent        REAL NOT NULL,
    passed         INTEGER NOT NULL,
    integrity_hash TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);

-- Неизменяемость результатов: после завершения сессии запрещены любые
-- изменения результата, вопросов теста и ответов.
CREATE TRIGGER trg_results_no_update BEFORE UPDATE ON test_results
BEGIN SELECT RAISE(ABORT, 'Результат тестирования неизменяем'); END;
CREATE TRIGGER trg_results_no_delete BEFORE DELETE ON test_results
BEGIN SELECT RAISE(ABORT, 'Результат тестирования не удаляется'); END;

CREATE TRIGGER trg_tq_lock_update BEFORE UPDATE ON test_questions
WHEN (SELECT status FROM test_sessions WHERE id = OLD.session_id) <> 'in_progress'
 AND NOT (NEW.question_id IS NULL AND OLD.question_id IS NOT NULL
          AND NEW.text = OLD.text AND NEW.options_json = OLD.options_json)
BEGIN SELECT RAISE(ABORT, 'Вопросы завершённого теста неизменяемы'); END;
CREATE TRIGGER trg_tq_lock_delete BEFORE DELETE ON test_questions
WHEN (SELECT status FROM test_sessions WHERE id = OLD.session_id) <> 'in_progress'
BEGIN SELECT RAISE(ABORT, 'Вопросы завершённого теста не удаляются'); END;

CREATE TRIGGER trg_ans_lock_update BEFORE UPDATE ON employee_answers
WHEN (SELECT s.status FROM test_sessions s JOIN test_questions q ON q.session_id = s.id
      WHERE q.id = OLD.test_question_id) <> 'in_progress'
BEGIN SELECT RAISE(ABORT, 'Ответы завершённого теста неизменяемы'); END;
CREATE TRIGGER trg_ans_lock_insert BEFORE INSERT ON employee_answers
WHEN (SELECT s.status FROM test_sessions s JOIN test_questions q ON q.session_id = s.id
      WHERE q.id = NEW.test_question_id) <> 'in_progress'
BEGIN SELECT RAISE(ABORT, 'Тест уже завершён'); END;
CREATE TRIGGER trg_ans_lock_delete BEFORE DELETE ON employee_answers
WHEN (SELECT s.status FROM test_sessions s JOIN test_questions q ON q.session_id = s.id
      WHERE q.id = OLD.test_question_id) <> 'in_progress'
BEGIN SELECT RAISE(ABORT, 'Ответы завершённого теста не удаляются'); END;

CREATE TRIGGER trg_session_lock BEFORE UPDATE ON test_sessions
WHEN OLD.status <> 'in_progress'
BEGIN SELECT RAISE(ABORT, 'Завершённая сессия тестирования неизменяема'); END;
CREATE TRIGGER trg_session_no_delete BEFORE DELETE ON test_sessions
WHEN OLD.status <> 'in_progress'
BEGIN SELECT RAISE(ABORT, 'Завершённая сессия не удаляется'); END;

CREATE TABLE backups (
    id            INTEGER PRIMARY KEY,
    file_path     TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('manual','auto','pre_restore')),
    size_bytes    INTEGER,
    sha256        TEXT,
    encrypted     INTEGER NOT NULL DEFAULT 0,
    integrity_ok  INTEGER,
    note          TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);
""")


def current_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def latest_version() -> int:
    return len(MIGRATIONS)


def migrate(conn: sqlite3.Connection) -> int:
    """Применяет недостающие миграции. Возвращает итоговую версию схемы."""
    ver = current_version(conn)
    if ver > latest_version():
        raise RuntimeError(
            f"База данных создана более новой версией программы (схема {ver}, "
            f"поддерживается до {latest_version()}). Обновите программу.")
    for idx in range(ver, latest_version()):
        script = MIGRATIONS[idx]
        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            conn.execute("BEGIN")
            for stmt in _split_sql(script):
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {idx + 1}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.execute("PRAGMA foreign_keys = ON")
    return current_version(conn)


def _split_sql(script: str) -> list[str]:
    """Разбивает скрипт на выражения, учитывая тела триггеров BEGIN…END."""
    stmts, buf = [], []
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buf.append(line)
        candidate = "\n".join(buf)
        if stripped.endswith(";") and sqlite3.complete_statement(candidate):
            stmts.append(candidate)
            buf = []
    if buf and "".join(buf).strip():
        stmts.append("\n".join(buf))
    return stmts
