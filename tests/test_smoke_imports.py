"""
Smoke test: every module under src/ must import cleanly.

Catches syntax errors, bad imports, NameErrors, and import-time side effects
before they show up at runtime in production.
"""
import importlib
import pkgutil
from pathlib import Path

import pytest

import src

REPO_ROOT = Path(__file__).resolve().parent.parent


def _all_src_modules():
    mods = []
    for finder, name, _ispkg in pkgutil.walk_packages(src.__path__, prefix="src."):
        # Skip __pycache__ artifacts
        if "__pycache__" in name:
            continue
        mods.append(name)
    return mods


@pytest.mark.parametrize("modname", _all_src_modules())
def test_module_imports(modname):
    importlib.import_module(modname)


def test_top_level_scripts_compile():
    """Top-level entrypoints (run.py, search.py, migrate_briefs.py) must compile."""
    import py_compile
    for name in ("run.py", "search.py", "migrate_briefs.py"):
        path = REPO_ROOT / name
        if path.exists():
            py_compile.compile(str(path), doraise=True)
