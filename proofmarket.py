#!/usr/bin/env python3
"""Convenience wrapper: `python proofmarket.py judge CASE EVIDENCE`.

It deliberately inserts its own directory even under ``python -I``, while never
adding the current working directory, so a planted ``json.py`` in an untrusted
data directory cannot shadow the standard library.
"""
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from proofmarket.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
