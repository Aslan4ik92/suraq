"""Локальная языковая модель через llama.cpp (llama-cpp-python).

Сетевые обращения отсутствуют: модель загружается из локального GGUF-файла.
"""
from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from typing import Protocol


class ModelNotConfigured(Exception):
    pass


class ModelLoadError(Exception):
    pass


@dataclass
class GenerationParams:
    temperature: float = 0.3
    top_p: float = 0.9
    max_tokens: int = 3072
    repeat_penalty: float = 1.1


class LLMBackend(Protocol):
    def chat(self, system: str, user: str, params: GenerationParams, json_mode: bool = True) -> str: ...

    def count_tokens(self, text: str) -> int: ...

    @property
    def n_ctx(self) -> int: ...


class LlamaCppBackend:
    def __init__(self, model_path: str, n_ctx: int = 8192, n_threads: int = 0, n_gpu_layers: int = 0):
        if not model_path:
            raise ModelNotConfigured("model_not_configured")
        if not os.path.isfile(model_path):
            raise ModelNotConfigured("model_not_found")
        try:
            from llama_cpp import Llama  # type: ignore
        except ImportError as e:
            raise ModelLoadError("llama_cpp_missing") from e
        threads = n_threads or max(1, (os.cpu_count() or 2) - 1)
        try:
            self._llm = Llama(model_path=model_path, n_ctx=n_ctx, n_threads=threads, n_gpu_layers=n_gpu_layers,
                              verbose=False, seed=-1)
        except Exception as e:
            raise ModelLoadError(f"model_load_failed: {e}") from e
        self._n_ctx = n_ctx
        self._lock = threading.Lock()
        self.model_path = model_path

    @property
    def n_ctx(self) -> int:
        return self._n_ctx

    def count_tokens(self, text: str) -> int:
        return len(self._llm.tokenize(text.encode("utf-8"), add_bos=False))

    def chat(self, system: str, user: str, params: GenerationParams, json_mode: bool = True) -> str:
        kwargs = dict(messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                      temperature=params.temperature, top_p=params.top_p, max_tokens=params.max_tokens,
                      repeat_penalty=params.repeat_penalty)
        with self._lock:
            if json_mode:
                try:
                    out = self._llm.create_chat_completion(response_format={"type": "json_object"}, **kwargs)
                except Exception:
                    out = self._llm.create_chat_completion(**kwargs)
            else:
                out = self._llm.create_chat_completion(**kwargs)
        return out["choices"][0]["message"]["content"] or ""

    def close(self) -> None:
        try:
            self._llm.close()
        except Exception:
            pass


_engine_lock = threading.Lock()
_engine: LlamaCppBackend | None = None
_engine_key: tuple | None = None


def get_engine(model_path: str, n_ctx: int, n_threads: int, n_gpu_layers: int) -> LlamaCppBackend:
    """Модель загружается один раз и переиспользуется."""
    global _engine, _engine_key
    key = (model_path, n_ctx, n_threads, n_gpu_layers)
    with _engine_lock:
        if _engine is not None and _engine_key == key:
            return _engine
        if _engine is not None:
            _engine.close()
            _engine = None
        _engine = LlamaCppBackend(model_path, n_ctx, n_threads, n_gpu_layers)
        _engine_key = key
        return _engine


def unload_engine() -> None:
    global _engine, _engine_key
    with _engine_lock:
        if _engine is not None:
            _engine.close()
        _engine, _engine_key = None, None


def extract_json(text: str):
    """Достаёт JSON из ответа модели (допускает обрамление ```json и лишний текст)."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.S).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        s, e = t.find(open_c), t.rfind(close_c)
        if s >= 0 and e > s:
            chunk = t[s:e + 1]
            try:
                return json.loads(chunk)
            except json.JSONDecodeError:
                fixed = re.sub(r",\s*([}\]])", r"\1", chunk)
                try:
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    continue
    raise ValueError("model_bad_json")
