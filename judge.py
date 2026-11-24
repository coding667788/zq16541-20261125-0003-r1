#!/usr/bin/env python3
"""Convenience entry point: python judge.py CASE EVIDENCE."""
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from proofmarket.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["judge", *sys.argv[1:]]))
