"""proofmarket: offline evidence procurement and verification."""

__version__ = "1.0.0"

from .buy import buy_best, price_selection
from .check import check_solution
from .judge import JudgeEngine, judge_case
from .loader import load_case, load_evidence

__all__ = [
    "JudgeEngine",
    "buy_best",
    "check_solution",
    "judge_case",
    "load_case",
    "load_evidence",
    "price_selection",
]
