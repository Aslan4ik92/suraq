"""Полнота локализации: все ключи интерфейса есть на русском и казахском."""
import re
import string
from pathlib import Path

from ibtest.localization import kk, ru
from ibtest.models.common import DIFFICULTIES, DocStatus, QStatus, QType

ROOT = Path(__file__).resolve().parents[1] / "ibtest"

DYNAMIC = (
    [f"st_{s}" for s in DocStatus.ALL + QStatus.ALL] +
    [f"st_{s}" for s in ("superseded", "added", "modified", "removed", "unchanged", "manual", "passed", "failed",
                         "not_tested", "retest")] +
    [f"anst_{s}" for s in ("not_started", "running", "done", "failed", "partial")] +
    [f"bk_kind_{k}" for k in ("manual", "auto", "pre_restore")] +
    [f"diff_{d}" for d in DIFFICULTIES] + [f"qt_{t}" for t in QType.ALL] + [f"emp_hint_{t}" for t in QType.ALL] +
    [f"lang_{l}" for l in ("ru", "kk", "other")] + [f"origin_{o}" for o in ("ai", "manual", "carried")] +
    [f"qa_{a}" for a in ("create", "approve", "reject", "edit", "submit", "obsolete", "to_draft")] +
    ["role_admin", "role_auditor", "carried_unchanged", "carried_modified", "carried_manual",
     "pwd_too_short", "pwd_need_digit", "pwd_need_letter", "pwd_need_case", "dash_documents", "dash_active_docs",
     "dash_approved_q", "an_not_tested",
     "q_bad_type", "q_text_short", "q_empty_option", "q_duplicate_options", "q_options_count", "q_need_one_correct",
     "q_need_multi_correct", "q_truefalse_shape", "q_bad_difficulty", "q_all_of_above",
     "model_not_gguf", "model_old_gguf", "model_read_error", "model_invalid", "ram_insufficient", "ram_low_free",
     "ctx_too_large", "ctx_small", "gpu_not_supported_build", "model_small_quality",
     "docx_has_macros", "txt_encoding_kz1048", "txt_encoding_cp1251", "text_has_replacement_chars",
     "pdf_page_needs_ocr"] +
    [f"progress_{p}" for p in ("ocr", "page", "batch", "done", "model_loading")]
)


def _literal_keys():
    keys = set()
    for p in ROOT.rglob("*.py"):
        if "localization" in p.parts:
            continue
        s = p.read_text(encoding="utf-8")
        keys |= {m for m in re.findall(r'\btr\(\s*"([a-z0-9_]+)"', s)}
        keys |= {m for m in re.findall(r'(?:Error|Rejected|Unavailable)\(\s*"([a-z0-9_]+)"', s)}
    return keys


def _audit_actions():
    acts = set()
    for p in ROOT.rglob("*.py"):
        s = p.read_text(encoding="utf-8")
        acts |= set(re.findall(r'audit\.log\(\s*"([a-z_]+)"', s))
    acts |= {f"question_{s}" for s in QStatus.ALL if s != "obsolete" or True}
    return {f"act_{a}" for a in acts}


def test_all_keys_present():
    need = _literal_keys() | set(DYNAMIC) | _audit_actions()
    need.discard("question_draft")
    missing_ru = sorted(k for k in need if k not in ru.STRINGS)
    missing_kk = sorted(k for k in need if k not in kk.STRINGS)
    assert not missing_ru, missing_ru
    assert not missing_kk, missing_kk


def test_same_keys_and_placeholders():
    assert set(ru.STRINGS) == set(kk.STRINGS), set(ru.STRINGS) ^ set(kk.STRINGS)
    f = string.Formatter()
    for k in ru.STRINGS:
        a = {x[1] for x in f.parse(ru.STRINGS[k]) if x[1]}
        b = {x[1] for x in f.parse(kk.STRINGS[k]) if x[1]}
        assert a == b, (k, a, b)


def test_kazakh_ui_has_kazakh_letters():
    text = " ".join(kk.STRINGS.values())
    for ch in "әғқңөұүі":
        assert ch in text
