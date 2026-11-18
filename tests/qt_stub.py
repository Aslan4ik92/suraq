"""Минимальная заглушка PySide6 для проверки логики интерфейса без Qt.

Используется только в автотестах, если PySide6 не установлен (CI без
графики). На рабочей машине с PySide6 тест интерфейса выполняется с
настоящим Qt в режиме offscreen."""
import sys
import types


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Stub

    def __or__(cls, other):
        return cls

    __ror__ = __or__


class _Stub(metaclass=_Meta):
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name in ("currentData", "data", "itemData", "currentWidget", "activeModalWidget"):
            return lambda *a, **k: None
        return _Stub()

    def __call__(self, *a, **k):
        return _Stub()

    def __bool__(self):
        return False

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def __int__(self):
        return 0

    def __index__(self):
        return 0

    def __float__(self):
        return 0.0

    def __str__(self):
        return ""

    def __or__(self, o):
        return self

    __ror__ = __and__ = __add__ = __radd__ = __sub__ = __mul__ = __truediv__ = __or__

    def __lt__(self, o):
        return False

    __gt__ = __le__ = __ge__ = __lt__

    def __eq__(self, o):
        return o is self

    __hash__ = object.__hash__


def install():
    if "PySide6" in sys.modules:
        return
    pkg = types.ModuleType("PySide6")
    pkg.__path__ = []
    for sub in ("QtCore", "QtGui", "QtWidgets", "QtPrintSupport"):
        m = types.ModuleType(f"PySide6.{sub}")
        m.__getattr__ = lambda name: _Stub  # noqa: E731
        sys.modules[f"PySide6.{sub}"] = m
        setattr(pkg, sub, m)
    sys.modules["PySide6"] = pkg
