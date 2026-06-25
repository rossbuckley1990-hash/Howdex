"""Pytest bootstrap — makes `howdex` importable from the source tree
without requiring `pip install`.

This is the standard pattern used by Flask, requests, urllib3, etc.
It inserts the project root onto sys.path before any test collects,
so `import howdex` works whether or not the package is installed.

If the package *is* installed (e.g. via `pip install -e .`), the installed
version takes precedence because site-packages comes first on sys.path.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Sanity check — fail fast with a clear message if the layout is broken
if not (ROOT / "howdex" / "__init__.py").exists():
    raise RuntimeError(
        f"conftest.py could not find the 'howdex' package at {ROOT}/howdex. "
        "Are you running pytest from the project root?"
    )
