# ИБ ТЕСТ — архитектура

## 1. Принципы

- **Полностью локальная работа.** Документы, ФИО, результаты и вопросы не покидают компьютер. Модель — GGUF-файл, исполняемый через llama.cpp в процессе программы; сетевых вызовов в коде нет.
- **Без подмены AI.** Если модель не подключена, генерация недоступна и программа предлагает её подключить. Шаблонных «псевдовопросов» нет.
- **Неизменяемая история.** Результаты, ответы и снимки вопросов теста защищены триггерами SQLite; журнал действий — только добавление.
- **Редакции не удаляются.** Каждая редакция приказа хранится с оригиналом файла, текстом, пунктами и вопросами.

## 2. Слои

```
ui/            PySide6: главное окно, 12 разделов, режим сотрудника (киоск), диалоги, фоновые задачи (QThread)
services/      Бизнес-логика, без зависимостей от Qt (покрыта автотестами)
  document_parser/   PDF (pdfium), DOCX (+ автонумерация Word), DOC (Word COM / LibreOffice), RTF, TXT, изображения;
                     проверка файлов; нормализация текста; разбиение на пункты; реквизиты приказа
  ocr/               Tesseract (rus+kaz+eng), поставляется с программой
  language/          определение ru/kk
  ai_engine/         llama.cpp-бэкенд, чтение заголовка GGUF, проверка ОЗУ/GPU/совместимости
  question_generator/ промпты RU/KZ, конвейер «требования → вопросы → проверка → самопроверка», повторный анализ
  version_comparator/ сопоставление пунктов редакций, пословный дифф
  documents.py       документы, редакции, перенос и актуализация вопросов, активация/восстановление
  questions.py       база вопросов, проверка структуры, утверждение, история
  test_engine/       профили тестирования, сбалансированная случайная выборка, сессии, подсчёт, контроль целостности
  analytics/         журнал результатов, карточка сотрудника, контроль прохождения, аналитика
  report_generator/  Excel (openpyxl), PDF (reportlab, шрифт DejaVu с казахскими буквами), HTML для печати
  backup/            резервные копии (SQLite backup API + оригиналы + манифест SHA-256, AES-256-GCM), восстановление
  security/          scrypt-хеши паролей, вход с блокировкой, журнал действий, DPAPI для секретов
database/      подключение SQLite (WAL, FULL sync, внешние ключи), миграции (PRAGMA user_version)
localization/  ru / kk (одинаковый набор ключей проверяется тестом)
config/        пути данных, настройки (таблица application_settings)
```

## 3. Хранение данных

| Что | Где |
|---|---|
| Программа | `C:\Program Files\IBTest` (только чтение) |
| База, документы, копии, модели, журнал | `C:\ProgramData\IBTest` (права «Пользователи: изменение», создаёт установщик) |
| Портативный запуск без установщика | `%LOCALAPPDATA%\IBTest`, если ProgramData недоступна |

ProgramData выбрана потому, что на одном компьютере тест проходят разные сотрудники под своими учётными записями Windows. Обновление и удаление программы не затрагивают эту папку (удаление спрашивает отдельно, по умолчанию — «Нет»).

## 4. Схема БД (SQLite, миграция v1)

```
departments(id, name, name_norm UNIQUE, is_active)
employees(id, uid, full_name, full_name_norm, department_id→departments, position, is_active)  UNIQUE(full_name_norm, department_id)
documents(id, uid, title, doc_number, doc_date, effective_date, language, status, active_version_id→document_versions, is_mandatory)
document_versions(id, uid, document_id→documents, version_no, file_name, stored_path, file_sha256, text_sha256,
                  raw_text, language, doc_number, doc_date, effective_date, ocr_used, status, analysis_state, activated_at)
document_sections(id, version_id→document_versions, order_index, number, heading, text, norm_hash, top_group)
document_changes(id, new_version_id, old_version_id, old_section_id, new_section_id, change_type, similarity, resolved, resolution)
requirements(id, uid, version_id, section_id, category, text, source_text)
questions(id, uid, document_id, version_id, section_id, requirement_id, parent_question_id, qtype, text, explanation,
          section_number, source_text, language, difficulty, status, previous_status, origin, review_note, norm_text, created_at)
question_options(id, question_id→questions CASCADE, order_index, text, is_correct)
question_approvals(id, question_id, admin_id, action, from_status, to_status, comment, created_at)
test_profiles(id, name, question_count, time_limit_min, pass_score, language, insufficient_policy, is_active, is_default)
test_profile_documents(profile_id, document_id, question_count)
test_sessions(id, uid, employee_id, profile_id, employee_name, department_name, position, language, question_count,
              pass_score, time_limit_min, question_set_hash, started_at, finished_at, duration_sec, status)
test_questions(id, session_id, order_index, question_id, question_uid, document_id, version_id, document_title, version_no,
               section_number, qtype, difficulty, text, options_json, explanation)      ← снимок вопроса и вариантов
employee_answers(id, test_question_id UNIQUE, selected_json, is_correct, answered_at)
test_results(id, session_id UNIQUE, total, correct, wrong, unanswered, percent, passed, integrity_hash)
admin_users(id, username, full_name, password_hash, role, is_active, failed_attempts, locked_until, last_login_at)
audit_logs(id, admin_id, username, action, entity, entity_id, details, created_at)
backups(id, file_path, kind, size_bytes, sha256, encrypted, integrity_ok, note, created_at)
application_settings(key, value, updated_at)
```

Триггеры: после завершения сессии запрещены UPDATE/DELETE для `test_results`, `test_sessions`, `test_questions`, `employee_answers`; `audit_logs` — только INSERT. Результат дополнительно подписан SHA-256 (`integrity_hash`) — карточка попытки показывает, совпадает ли контрольная сумма.

Текстовые сравнения ФИО и подразделений выполняются по нормализованным полям (`*_norm`), потому что `COLLATE NOCASE` в SQLite не работает для кириллицы.

## 5. Генерация вопросов

1. Текст разбивается на пункты (`1.`, `1.1.`, `2.3.4`, главы/разделы, казахские «тарау/бөлім/бап»); для Word восстанавливается автоматическая нумерация.
2. Пункты упаковываются в фрагменты по размеру контекста модели.
3. **Проход 1 — требования.** Модель возвращает JSON: номер пункта, категория, формулировка, *дословная цитата*. Требование без цитаты, найденной в тексте пункта, отбрасывается.
4. **Проход 2 — вопросы** по группам из 5 требований: 4 типа, сложность, объяснение, цитата-основание.
5. **Программная проверка:** структура (ровно один правильный ответ для single/situational, 2+ для multiple, запрет «все перечисленное»), привязка цитаты к тексту пункта, дубликаты (сходство слов ≥ 0,85).
6. **Проход 3 — самопроверка** (по умолчанию включена): модель оценивает, нет ли второго правильного варианта или сведений не из документа.
7. Все вопросы сохраняются со статусом «На проверке». В тест попадают только утверждённые вопросы действующей редакции.

Для казахских документов инструкции модели даются на казахском, текст не переводится. Язык вопросов можно выбрать вручную.

Количество вопросов не ограничено: по умолчанию 2 вопроса на каждое выделенное требование (настраивается 1–6). Документ на 80–100 требований даёт 150–200 вопросов.

## 6. Редакции

Сравнение пунктов: (1) совпадение нормализованного текста без номера — без изменений (перенумерация не считается изменением); (2) тот же номер и сходство ≥ 0,45 — изменён; (3) иной номер и сходство ≥ 0,80 — изменён (перенесён); 0,55–0,80 — **ручная проверка**; остальные — добавлены/удалены. Нормализация игнорирует регистр, кавычки, тире, ё/е, пробелы, маркеры списков и конечную пунктуацию.

Актуализация при загрузке редакции: утверждённые вопросы неизменённых пунктов копируются в новую редакцию утверждёнными; вопросы изменённых и неоднозначных пунктов — копируются «На проверке»; вопросы удалённых пунктов не переносятся. Генерация запускается по добавленным/изменённым пунктам. Активация делает новую редакцию действующей, вопросы прежней помечаются «Устарел» (с сохранением прежнего статуса), что позволяет восстановить прежнюю редакцию.

## 7. Тестирование

Выборка балансируется по разделам документа (квоты пропорционально числу вопросов раздела, минимум по одному) и сложности (30/50/20 %). Порядок вопросов и вариантов перемешивается (кроме «Верно/Неверно»). Хеш набора сравнивается с 20 последними попытками сотрудника — повторяющийся набор пересобирается. При нехватке вопросов профиль либо блокирует тест (по умолчанию), либо разрешает тест из меньшего числа вопросов без повторов.

Ответы сохраняются в БД сразу после выбора; таймер проверяется и на сервере сессии; незавершённые после сбоя сессии закрываются при следующем запуске.

## 8. Безопасность

- Пароли: scrypt (N=2^15, r=8, p=1), блокировка после 5 неудачных попыток на 5 минут, автовыход при бездействии.
- Пароль шифрования копий хранится через DPAPI (область компьютера).
- Загружаемые файлы проверяются по расширению, сигнатуре, размеру, «zip-бомбе»; макросы DOCX не исполняются.
- SQLite не шифруется: база защищена правами NTFS на ProgramData и BitLocker (рекомендуется), копии — AES-256-GCM.

## 9. Установщик

- `installer/build.ps1`: виртуальное окружение Python 3.12 → llama-cpp-python (CPU или CUDA) → загрузка Tesseract + rus/kaz/eng → VC++ Runtime → автотесты → PyInstaller (onedir) → `IBTest.exe --selftest` → Inno Setup.
- `installer/ibtest.iss`: Program Files, ярлыки (обычный и «режим тестирования»), ProgramData с правами, VC++ Runtime при отсутствии, удаление через «Установленные приложения», данные не удаляются при обновлении. Модель ставится вместе с программой, если файл `.gguf` лежит в папке `models` рядом с Setup.exe.
- `installer/ibtest_model.iss`: отдельный пакет модели (DiskSpanning для файлов > 4 ГБ).
