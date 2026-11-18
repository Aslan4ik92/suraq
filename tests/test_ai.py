import struct

import pytest

from ibtest.services.ai_engine import system_check
from ibtest.services.ai_engine.llm import LlamaCppBackend, ModelNotConfigured, extract_json
from ibtest.services.question_generator.generator import parse_question, quote_grounded


def _gguf(path, arch="qwen2", ctx=32768, ftype=15, name="Qwen2.5-7B-Instruct"):
    def s(x):
        b = x.encode()
        return struct.pack("<Q", len(b)) + b
    kv = [(s("general.architecture"), 8, s(arch)), (s("general.name"), 8, s(name)),
          (s("general.file_type"), 4, struct.pack("<I", ftype)),
          (s(f"{arch}.context_length"), 4, struct.pack("<I", ctx))]
    body = b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", 0, len(kv))
    for k, t, v in kv:
        body += k + struct.pack("<I", t) + v
    path.write_bytes(body + b"\x00" * 1024)
    return path


def test_inspect_gguf(tmp_path):
    info = system_check.inspect_model(_gguf(tmp_path / "m.gguf"))
    assert info.valid and info.architecture == "qwen2" and info.context_length == 32768
    assert info.quantization == "Q4_K_M" and info.name.startswith("Qwen")
    bad = tmp_path / "x.gguf"
    bad.write_bytes(b"NOTGGUF")
    assert system_check.inspect_model(bad).error == "model_not_gguf"


def test_compatibility_ram():
    sysinfo = system_check.SystemInfo("Windows 10", 8, 8.0, 6.0, False, llama_cpp_version="0.3")
    model = system_check.ModelInfo("m", 7.5, True, 3, "llama", "x", 8192, "", "Q8_0")
    c = system_check.check_compatibility(model, sysinfo, 8192, 0)
    assert not c.ok and c.errors[0].startswith("ram_insufficient")
    model.size_gb = 4.7
    c = system_check.check_compatibility(model, sysinfo, 16384, 20)
    assert c.ok
    assert any(w.startswith("ctx_too_large") for w in c.warnings)
    assert "gpu_not_supported_build" in c.warnings


def test_no_model_no_fallback(tmp_path):
    with pytest.raises(ModelNotConfigured):
        LlamaCppBackend("")
    with pytest.raises(ModelNotConfigured):
        LlamaCppBackend(str(tmp_path / "missing.gguf"))


def test_generator_requires_model(ctx):
    with pytest.raises(ModelNotConfigured):
        ctx.make_generator()


def test_extract_json_variants():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Вот ответ: {"a": [1, 2,],}') == {"a": [1, 2]}
    assert extract_json('<think>...</think>{"q": "Құпиясөз"}') == {"q": "Құпиясөз"}
    with pytest.raises(ValueError):
        extract_json("нет json")


def test_parse_question_shapes():
    q = parse_question({"type": "truefalse", "question": "Пароль можно сообщать руководителю.", "answer": False,
                        "quote": "Запрещается передавать свой пароль"}, "ru")
    assert [o.text for o in q.options] == ["Верно", "Неверно"] and q.options[1].is_correct
    q = parse_question({"type": "multiple", "question": "Что должен содержать пароль?",
                        "options": ["A) Цифры", "B) Буквы", "C) Имя", "D) Дату"], "correct": [0, 1]}, "kk")
    assert q.options[0].text == "Цифры" and q.correct_indices() == [0, 1]
    assert parse_question({"type": "single", "question": "x", "options": ["a"], "correct": [5]}, "ru") is None


def test_quote_grounding():
    src = "2.1. Пароль учётной записи должен содержать не менее 12 символов, включая прописные и строчные буквы."
    assert quote_grounded("Пароль учётной записи должен содержать не менее 12 символов", src)
    assert quote_grounded("пароль учетной записи должен содержать не менее 12 символов", src)  # ё/е, регистр
    assert not quote_grounded("Пароль меняется каждые 30 дней администратором системы", src)
