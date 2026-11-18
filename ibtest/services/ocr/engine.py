"""Локальное распознавание текста (Tesseract OCR).

Tesseract поставляется вместе с установщиком (папка {app}\\tesseract) с
языковыми моделями rus, kaz, eng. Данные никуда не передаются.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageOps

from ibtest.config import paths


class OcrUnavailable(Exception):
    pass


class OcrEngine:
    def __init__(self, tesseract_path: str = "", languages: str = "rus+kaz+eng"):
        self.tesseract_path = tesseract_path
        self.languages = languages
        self._exe: str | None = None
        self._langs: set[str] | None = None

    def executable(self) -> str:
        if self._exe:
            return self._exe
        cands = [self.tesseract_path] if self.tesseract_path else []
        bundled = paths.bundled_tesseract()
        if bundled:
            cands.append(str(bundled))
        if sys.platform == "win32":
            cands += [r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                      r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"]
        found = shutil.which("tesseract")
        if found:
            cands.append(found)
        for c in cands:
            if c and Path(c).exists():
                self._exe = c
                return c
        raise OcrUnavailable("ocr_not_found")

    def available_languages(self) -> set[str]:
        if self._langs is None:
            out = self._run([self.executable(), "--list-langs"])
            self._langs = {l.strip() for l in out.splitlines()[1:] if l.strip()}
        return self._langs

    def effective_languages(self) -> str:
        have = self.available_languages()
        want = [l for l in self.languages.split("+") if l]
        use = [l for l in want if l in have]
        if not use:
            raise OcrUnavailable("ocr_no_languages")
        return "+".join(use)

    def missing_languages(self) -> list[str]:
        try:
            have = self.available_languages()
        except OcrUnavailable:
            return self.languages.split("+")
        return [l for l in self.languages.split("+") if l and l not in have]

    def is_available(self) -> bool:
        try:
            self.executable()
            return True
        except OcrUnavailable:
            return False

    def _run(self, args: list[str], input_bytes: bytes | None = None) -> str:
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        exe_dir = Path(args[0]).parent
        env = None
        tessdata = exe_dir / "tessdata"
        if tessdata.exists():
            import os
            env = dict(os.environ, TESSDATA_PREFIX=str(tessdata))
        proc = subprocess.run(args, input=input_bytes, capture_output=True, timeout=300, env=env, **kwargs)
        if proc.returncode != 0:
            raise OcrUnavailable(proc.stderr.decode("utf-8", errors="replace")[:500] or "ocr_failed")
        return proc.stdout.decode("utf-8", errors="replace")

    def image_to_text(self, image: Image.Image) -> str:
        img = ImageOps.exif_transpose(image).convert("L")
        if img.width < 1500:
            scale = 1500 / max(img.width, 1)
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        tmp = paths.tmp_dir() / f"ocr_{id(img)}.png"
        img.save(tmp)
        try:
            return self._run([self.executable(), str(tmp), "stdout", "-l", self.effective_languages(),
                              "--psm", "3"])
        finally:
            tmp.unlink(missing_ok=True)

    def file_to_text(self, path: Path) -> str:
        with Image.open(path) as im:
            frames = []
            try:
                i = 0
                while True:
                    im.seek(i)
                    frames.append(self.image_to_text(im.copy()))
                    i += 1
            except EOFError:
                pass
        return "\n\n".join(frames)
