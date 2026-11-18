"""Точка входа «ИБ ТЕСТ»."""
import sys

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        from ibtest.selftest import run as selftest
        i = sys.argv.index("--selftest")
        sys.exit(selftest(sys.argv[i + 1] if len(sys.argv) > i + 1 else None))
    from ibtest.ui.app import run
    sys.exit(run(sys.argv[1:]))
