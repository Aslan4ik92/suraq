# -*- mode: python ; coding: utf-8 -*-
# Сборка: pyinstaller installer\ibtest.spec --noconfirm  (из корня проекта)
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from ibtest import __version__  # noqa: E402

datas, binaries, hiddenimports = [], [], []
for pkg in ("llama_cpp", "pypdfium2", "pypdfium2_raw", "reportlab"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:  # пакет может отсутствовать в окружении сборки
        print(f"WARNING: {pkg}: {e}")
hiddenimports += collect_submodules("ibtest")
hiddenimports += ["win32com.client", "pythoncom", "pywintypes"]
datas += [(str(ROOT / "ibtest" / "assets"), "ibtest/assets")]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="IBTest",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / "ibtest" / "assets" / "ibtest.ico"),
    version=str(ROOT / "installer" / "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="IBTest")
