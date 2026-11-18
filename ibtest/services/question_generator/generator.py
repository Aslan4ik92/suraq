"""Анализ требований и генерация вопросов локальной моделью.

Конвейер для каждой порции пунктов:
 1. выделение требований (с дословной цитатой и номером пункта);
 2. генерация вопросов по группам требований;
 3. программная проверка: структура, привязка цитаты к тексту пункта,
    дубликаты;
 4. самопроверка моделью (необязательный второй проход).
Все вопросы сохраняются со статусом «На проверке» и попадают в тестирование
только после утверждения администратором.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Callable

from ibtest.database.connection import Database
from ibtest.models.common import DIFFICULTIES, OptionData, QStatus, QType, QuestionData, TRUE_FALSE_LABELS, new_uid, now_iso
from ibtest.services.ai_engine.llm import GenerationParams, LLMBackend, extract_json
from ibtest.services.document_parser.sections import normalize_for_compare
from ibtest.services.question_generator import prompts
from ibtest.services.questions import QuestionError, QuestionService, validate_question
from ibtest.services.security.auth import AuditLog

log = logging.getLogger(__name__)

Progress = Callable[[int, int, str], None]

_WORD = re.compile(r"\w+", re.U)


class GenerationCancelled(Exception):
    pass


@dataclass
class GenerationStats:
    batches: int = 0
    requirements: int = 0
    generated: int = 0
    saved: int = 0
    rejected_structure: int = 0
    rejected_grounding: int = 0
    rejected_duplicate: int = 0
    rejected_verify: int = 0
    model_errors: int = 0
    messages: list[str] = field(default_factory=list)


def quote_grounded(quote: str, source: str, min_cover: float = 0.75) -> bool:
    """Цитата должна присутствовать в тексте пункта (точно или почти дословно)."""
    q, s = normalize_for_compare(quote), normalize_for_compare(source)
    if not q:
        return False
    if q in s:
        return True
    qt = [w for w in _WORD.findall(q) if len(w) > 2]
    if len(qt) < 3:
        return False
    st = set(_WORD.findall(s))
    cover = sum(1 for w in qt if w in st) / len(qt)
    if cover < min_cover:
        return False
    # Порядок слов: длинная общая подпоследовательность.
    s_words = _WORD.findall(s)
    pos, hits = 0, 0
    for w in qt:
        try:
            pos = s_words.index(w, pos) + 1
            hits += 1
        except ValueError:
            continue
    return hits / len(qt) >= min_cover - 0.1


def _section_block(secs: list) -> str:
    return "\n\n".join(f"[{s['number'] or s['id']}] {s['text']}" for s in secs)


def _pack(secs: list, max_chars: int) -> list[list]:
    batches, cur, size = [], [], 0
    for s in secs:
        t = len(s["text"]) + 12
        if cur and size + t > max_chars:
            batches.append(cur)
            cur, size = [], 0
        if t > max_chars:
            # Очень длинный пункт режется на части по абзацам.
            parts, buf = [], ""
            for para in s["text"].split("\n"):
                if buf and len(buf) + len(para) > max_chars:
                    parts.append(buf)
                    buf = ""
                buf += ("\n" if buf else "") + para
            if buf:
                parts.append(buf)
            for i, ptxt in enumerate(parts):
                batches.append([dict(s, text=ptxt, _part=i + 1)])
            continue
        cur.append(s)
        size += t
    if cur:
        batches.append(cur)
    return batches


def parse_question(item: dict, language: str) -> QuestionData | None:
    """Преобразует ответ модели в QuestionData; None — если форма неверна."""
    try:
        qtype = str(item.get("type", "single")).strip().lower()
        if qtype not in QType.ALL:
            qtype = QType.SINGLE
        text = str(item.get("question", "")).strip()
        diff = str(item.get("difficulty", "medium")).lower()
        if diff not in DIFFICULTIES:
            diff = "medium"
        if qtype == QType.TRUEFALSE:
            ans = item.get("answer")
            if isinstance(ans, str):
                ans = ans.strip().lower() in ("true", "верно", "дұрыс", "да", "иә", "1")
            if not isinstance(ans, bool):
                corr = item.get("correct")
                if isinstance(corr, list) and corr in ([0], [1]):
                    ans = corr == [0]
                else:
                    return None
            lab = TRUE_FALSE_LABELS[language]
            options = [OptionData(lab[0], ans), OptionData(lab[1], not ans)]
        else:
            opts = [str(o).strip() for o in item.get("options", []) if str(o).strip()]
            corr = item.get("correct", [])
            if isinstance(corr, int):
                corr = [corr]
            corr = {int(c) for c in corr if isinstance(c, (int, float, str)) and str(c).lstrip("-").isdigit()}
            if not opts or any(c < 0 or c >= len(opts) for c in corr):
                return None
            options = [OptionData(re.sub(r"^[A-DА-Га-гa-d1-6][\)\.]\s+", "", o), i in corr) for i, o in enumerate(opts)]
        return QuestionData(qtype=qtype, text=text, options=options,
                            explanation=str(item.get("explanation", "")).strip(),
                            section_number=str(item.get("section", "")).strip().strip("[]"),
                            source_text=str(item.get("quote", "")).strip(), language=language, difficulty=diff)
    except (TypeError, ValueError, AttributeError):
        return None


class QuestionGenerator:
    def __init__(self, db: Database, questions: QuestionService, audit: AuditLog, backend: LLMBackend,
                 params: GenerationParams, chunk_chars: int = 6000, per_requirement: int = 2, verify: bool = True):
        self.db, self.questions, self.audit, self.llm = db, questions, audit, backend
        self.params, self.chunk_chars, self.per_req, self.verify = params, chunk_chars, per_requirement, verify

    # -- общий вызов модели ------------------------------------------------------
    def _ask(self, lang: str, user: str, max_tokens: int | None = None):
        p = self.params
        if max_tokens:
            p = GenerationParams(p.temperature, p.top_p, max_tokens, p.repeat_penalty)
        last = None
        for attempt in range(2):
            raw = self.llm.chat(prompts.SYSTEM[lang], user, p, json_mode=True)
            try:
                return extract_json(raw)
            except ValueError as e:
                last = e
                log.warning("model returned invalid JSON (attempt %s): %s", attempt + 1, raw[:300])
        raise last  # type: ignore[misc]

    def _fit(self, text: str) -> bool:
        try:
            return self.llm.count_tokens(text) + self.params.max_tokens + 300 <= self.llm.n_ctx
        except Exception:
            return True

    # -- основной метод ------------------------------------------------------------
    def generate_for_version(self, version_id: int, section_ids: list[int] | None = None,
                             language: str | None = None, progress: Progress | None = None,
                             cancel: threading.Event | None = None) -> GenerationStats:
        v = self.db.one("SELECT v.*, d.title, d.id AS doc_id FROM document_versions v JOIN documents d "
                        "ON d.id = v.document_id WHERE v.id = ?", (version_id,))
        if v is None:
            raise ValueError("version_not_found")
        lang = language or v["language"]
        if lang not in ("ru", "kk"):
            lang = "ru"
        secs = [dict(r) for r in self.db.query("SELECT * FROM document_sections WHERE version_id = ? ORDER BY order_index",
                                               (version_id,))]
        if section_ids is not None:
            wanted = set(section_ids)
            secs = [s for s in secs if s["id"] in wanted]
        secs = [s for s in secs if len(s["text"]) >= 40 and s["top_group"] != "преамбула"]
        stats = GenerationStats()
        batches = _pack(secs, self.chunk_chars)
        stats.batches = len(batches)
        self.db.execute("UPDATE document_versions SET analysis_state = 'running' WHERE id = ?", (version_id,))
        try:
            for bi, batch in enumerate(batches):
                if cancel and cancel.is_set():
                    raise GenerationCancelled()
                if progress:
                    progress(bi, len(batches), "batch")
                try:
                    self._process_batch(v, lang, batch, stats, cancel)
                except GenerationCancelled:
                    raise
                except Exception as e:  # ошибка одной порции не прерывает весь анализ
                    stats.model_errors += 1
                    stats.messages.append(f"batch {bi + 1}: {e}")
                    log.exception("batch failed")
            state = "done" if stats.model_errors == 0 else ("partial" if stats.saved else "failed")
        except GenerationCancelled:
            state = "partial" if stats.saved else "not_started"
            stats.messages.append("cancelled")
        self.db.execute("UPDATE document_versions SET analysis_state = ? WHERE id = ?", (state, version_id))
        if progress:
            progress(len(batches), len(batches), "done")
        self.audit.log("questions_generate", "document_versions", version_id,
                       {k: getattr(stats, k) for k in ("batches", "requirements", "generated", "saved",
                                                       "rejected_structure", "rejected_grounding",
                                                       "rejected_duplicate", "rejected_verify", "model_errors")})
        return stats

    def _process_batch(self, v, lang: str, batch: list, stats: GenerationStats, cancel) -> None:
        block = _section_block(batch)
        by_num = {str(s["number"] or s["id"]): s for s in batch}
        user = prompts.EXTRACT[lang].format(title=v["title"], categories=", ".join(prompts.CATEGORIES), sections=block)
        if not self._fit(user):
            raise ValueError("chunk_too_large_for_context")
        data = self._ask(lang, user)
        reqs_raw = data.get("requirements", []) if isinstance(data, dict) else []
        reqs = []
        for r in reqs_raw:
            if not isinstance(r, dict) or not str(r.get("text", "")).strip():
                continue
            sec = by_num.get(str(r.get("section", "")).strip().strip("[]"))
            quote = str(r.get("quote", ""))
            if sec is None or not quote_grounded(quote, sec["text"]):
                # Номер не распознан — ищем пункт, где встречается цитата.
                sec = next((s for s in batch if quote_grounded(quote, s["text"])), None)
            if sec is None:
                continue
            cat = str(r.get("category", "other"))
            cur = self.db.execute(
                "INSERT INTO requirements(uid, version_id, section_id, category, text, source_text, created_at) "
                "VALUES (?,?,?,?,?,?,?)", (new_uid("r_"), v["id"], sec["id"],
                                           cat if cat in prompts.CATEGORIES else "other",
                                           str(r["text"]).strip(), quote.strip(), now_iso()))
            reqs.append({"id": cur.lastrowid, "section": sec, "text": str(r["text"]).strip()})
        stats.requirements += len(reqs)
        for g in range(0, len(reqs), 5):
            if cancel and cancel.is_set():
                raise GenerationCancelled()
            self._questions_for_group(v, lang, reqs[g:g + 5], stats)

    def _questions_for_group(self, v, lang: str, group: list, stats: GenerationStats) -> None:
        secs = {r["section"]["id"]: r["section"] for r in group}
        req_block = "\n".join(f"{i + 1}. [{r['section']['number'] or r['section']['id']}] {r['text']}"
                              for i, r in enumerate(group))
        user = prompts.QUESTIONS[lang].format(title=v["title"], per_req=self.per_req, requirements=req_block,
                                              sections=_section_block(list(secs.values())))
        data = self._ask(lang, user)
        items = data.get("questions", []) if isinstance(data, dict) else []
        candidates: list[tuple[QuestionData, dict, dict]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            stats.generated += 1
            q = parse_question(it, lang)
            if q is None or validate_question(q):
                stats.rejected_structure += 1
                continue
            try:
                req = group[int(it.get("requirement", 1)) - 1]
            except (ValueError, IndexError, TypeError):
                req = group[0]
            sec = req["section"]
            if not quote_grounded(q.source_text, sec["text"]):
                other = next((s for s in secs.values() if quote_grounded(q.source_text, s["text"])), None)
                if other is None:
                    stats.rejected_grounding += 1
                    continue
                sec = other
            q.section_number = sec["number"] or ""
            if self.questions.find_duplicate(v["id"], q.text) or any(
                    _similar(q.text, c[0].text) for c in candidates):
                stats.rejected_duplicate += 1
                continue
            candidates.append((q, req, sec))
        if self.verify and candidates:
            candidates = self._verify(lang, candidates, stats)
        for q, req, sec in candidates:
            try:
                self.questions.create(q, v["doc_id"], v["id"], sec["id"], req["id"], status=QStatus.REVIEW, origin="ai")
                stats.saved += 1
            except QuestionError:
                stats.rejected_structure += 1

    def _verify(self, lang: str, cands: list, stats: GenerationStats) -> list:
        secs = {}
        for _, _, s in cands:
            secs[s["id"]] = s
        qblock = []
        for i, (q, _, _) in enumerate(cands, start=1):
            opts = "; ".join(f"{'[+]' if o.is_correct else '[-]'} {o.text}" for o in q.options)
            qblock.append(f"{i}. ({q.qtype}) {q.text}\n   {opts}")
        user = prompts.VERIFY[lang].format(sections=_section_block(list(secs.values())), questions="\n".join(qblock))
        try:
            data = self._ask(lang, user, max_tokens=1200)
            verdicts = {int(x.get("id")): x for x in data.get("verdicts", []) if isinstance(x, dict) and "id" in x}
        except Exception as e:
            stats.messages.append(f"verify failed: {e}")
            return cands  # без самопроверки вопросы всё равно проходят ручное утверждение
        keep = []
        for i, c in enumerate(cands, start=1):
            vd = verdicts.get(i)
            if vd is not None and vd.get("valid") is False:
                stats.rejected_verify += 1
                continue
            keep.append(c)
        return keep

    # -- повторный анализ одного вопроса ---------------------------------------
    def reanalyze(self, qid: int) -> tuple[bool, str]:
        row = self.questions.get(qid)
        if row is None:
            raise ValueError("q_not_found")
        data = self.questions.as_data(qid)
        lang = row["language"]
        q_txt = json.dumps({"type": data.qtype, "question": data.text,
                            "options": [o.text for o in data.options], "correct": data.correct_indices(),
                            "explanation": data.explanation}, ensure_ascii=False)
        section_text = row["section_text"] or row["source_text"] or ""
        if not section_text:
            raise ValueError("q_no_source")
        user = prompts.REANALYZE[lang].format(qtype=data.qtype, section_number=row["section_number"] or "",
                                              section_text=section_text, question=q_txt)
        res = self._ask(lang, user, max_tokens=1500)
        ok = bool(res.get("ok", False))
        comment = str(res.get("comment", "")).strip()
        if not ok and isinstance(res.get("question"), dict):
            item = dict(res["question"], type=data.qtype)
            new_q = parse_question(item, lang)
            if new_q is None or validate_question(new_q):
                return False, comment or "model_bad_fix"
            new_q.section_number = data.section_number
            if not quote_grounded(new_q.source_text, section_text):
                new_q.source_text = data.source_text
            self.questions.update(qid, new_q, note="ai_reanalyze: " + comment)
            self.db.execute("UPDATE questions SET status = 'review', review_note = ? WHERE id = ?",
                            (("AI: " + comment)[:500], qid))
            return False, comment
        self.db.execute("UPDATE questions SET review_note = ? WHERE id = ?", ("AI: OK", qid))
        self.audit.log("question_reanalyze", "questions", qid, {"ok": ok})
        return True, comment


def _similar(a: str, b: str, threshold: float = 0.85) -> bool:
    wa, wb = set(_WORD.findall(a.lower())), set(_WORD.findall(b.lower()))
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= threshold
