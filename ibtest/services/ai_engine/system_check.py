"""Проверка аппаратных ресурсов и совместимости GGUF-модели."""
from __future__ import annotations

import ctypes
import os
import platform
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SystemInfo:
    os: str
    cpu_count: int
    ram_total_gb: float
    ram_free_gb: float
    gpu_offload: bool
    gpu_name: str = ""
    llama_cpp_version: str = ""
    avx2: bool | None = None


@dataclass
class ModelInfo:
    path: str
    size_gb: float
    valid: bool
    gguf_version: int = 0
    architecture: str = ""
    name: str = ""
    context_length: int = 0
    file_type: str = ""
    quantization: str = ""
    error: str = ""


@dataclass
class Compatibility:
    ok: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def memory_gb() -> tuple[float, float]:
    if sys.platform == "win32":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
        st = MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))  # type: ignore[attr-defined]
        return st.ullTotalPhys / 2 ** 30, st.ullAvailPhys / 2 ** 30
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.strip().split()[0]) * 1024
        return info["MemTotal"] / 2 ** 30, info.get("MemAvailable", info["MemFree"]) / 2 ** 30
    except OSError:
        return 0.0, 0.0


def _windows_gpu_name() -> str:
    if sys.platform != "win32":
        return ""
    try:
        import subprocess
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "(Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name) -join '; '"],
                             capture_output=True, timeout=10, creationflags=0x08000000)
        return out.stdout.decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


def system_info() -> SystemInfo:
    total, free = memory_gb()
    gpu, ver = False, ""
    try:
        import llama_cpp  # type: ignore
        ver = getattr(llama_cpp, "__version__", "")
        fn = getattr(llama_cpp, "llama_supports_gpu_offload", None)
        gpu = bool(fn()) if fn else False
    except Exception:
        pass
    return SystemInfo(os=f"{platform.system()} {platform.release()} {platform.machine()}",
                      cpu_count=os.cpu_count() or 1, ram_total_gb=round(total, 1), ram_free_gb=round(free, 1),
                      gpu_offload=gpu, gpu_name=_windows_gpu_name(), llama_cpp_version=ver)


# -- чтение заголовка GGUF ---------------------------------------------------------
_GGUF_TYPES = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
_FILE_TYPES = {0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1", 10: "Q2_K",
               11: "Q3_K_S", 12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M", 16: "Q5_K_S",
               17: "Q5_K_M", 18: "Q6_K", 19: "IQ2_XXS", 20: "IQ2_XS", 24: "IQ1_S", 25: "IQ4_NL",
               26: "IQ3_S", 27: "IQ3_M", 28: "IQ2_S", 29: "IQ2_M", 30: "IQ4_XS", 32: "BF16"}


def _read_str(f) -> str:
    (n,) = struct.unpack("<Q", f.read(8))
    if n > 1 << 20:
        raise ValueError("bad string length")
    return f.read(n).decode("utf-8", errors="replace")


def _read_value(f, t: int):
    if t in _GGUF_TYPES:
        fmt = "<" + _GGUF_TYPES[t]
        return struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0]
    if t == 8:
        return _read_str(f)
    if t == 9:
        (et,) = struct.unpack("<I", f.read(4))
        (n,) = struct.unpack("<Q", f.read(8))
        if et == 8:
            for _ in range(n):
                _read_str(f)
        else:
            size = struct.calcsize("<" + _GGUF_TYPES[et])
            f.seek(size * n, 1)
        return f"<array {n}>"
    raise ValueError(f"unknown type {t}")


def inspect_model(path: str | Path) -> ModelInfo:
    p = Path(path)
    if not p.is_file():
        return ModelInfo(str(p), 0, False, error="model_not_found")
    size = p.stat().st_size / 2 ** 30
    info = ModelInfo(str(p), round(size, 2), False)
    try:
        with open(p, "rb") as f:
            if f.read(4) != b"GGUF":
                info.error = "model_not_gguf"
                return info
            (ver,) = struct.unpack("<I", f.read(4))
            info.gguf_version = ver
            if ver < 2:
                info.error = "model_old_gguf"
                return info
            _tensors, kv_count = struct.unpack("<QQ", f.read(16))
            meta = {}
            for _ in range(min(kv_count, 4096)):
                key = _read_str(f)
                (t,) = struct.unpack("<I", f.read(4))
                val = _read_value(f, t)
                if key in ("general.architecture", "general.name", "general.file_type") or key.endswith(".context_length"):
                    meta[key] = val
                if len(meta) >= 4 and "general.architecture" in meta and any(k.endswith(".context_length") for k in meta):
                    break
        info.architecture = str(meta.get("general.architecture", ""))
        info.name = str(meta.get("general.name", p.stem))
        ctx_key = f"{info.architecture}.context_length"
        info.context_length = int(meta.get(ctx_key, 0) or 0)
        ft = meta.get("general.file_type")
        info.quantization = _FILE_TYPES.get(int(ft), str(ft)) if ft is not None else ""
        info.valid = True
    except Exception as e:
        info.error = f"model_read_error: {e}"
    return info


def check_compatibility(model: ModelInfo, sysinfo: SystemInfo, n_ctx: int, n_gpu_layers: int) -> Compatibility:
    c = Compatibility(ok=True)
    if not model.valid:
        c.ok = False
        c.errors.append(model.error or "model_invalid")
        return c
    # Оценка: веса + KV-кэш (~0.5 ГБ на 4k контекста для 7–8B) + накладные расходы.
    need = model.size_gb + 0.6 * (n_ctx / 4096) + 0.8
    if n_gpu_layers != 0 and sysinfo.gpu_offload:
        need = max(1.5, need * 0.35)  # основная часть весов в видеопамяти
    if sysinfo.ram_total_gb and need > sysinfo.ram_total_gb:
        c.ok = False
        c.errors.append(f"ram_insufficient:{need:.1f}:{sysinfo.ram_total_gb:.1f}")
    elif sysinfo.ram_free_gb and need > sysinfo.ram_free_gb:
        c.warnings.append(f"ram_low_free:{need:.1f}:{sysinfo.ram_free_gb:.1f}")
    if model.context_length and n_ctx > model.context_length:
        c.warnings.append(f"ctx_too_large:{model.context_length}")
    if n_ctx < 4096:
        c.warnings.append("ctx_small")
    if n_gpu_layers != 0 and not sysinfo.gpu_offload:
        c.warnings.append("gpu_not_supported_build")
    if model.size_gb < 2.0:
        c.warnings.append("model_small_quality")
    if not sysinfo.llama_cpp_version:
        c.ok = False
        c.errors.append("llama_cpp_missing")
    return c
