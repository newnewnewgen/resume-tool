"""Eval harness: golden requirement → experience pairs with known answers.

Exists before retrieval does (build step 2) so that step 5 is built against a
measurable target instead of vibes — learning #1 from the postmortem.
"""

from .golden import GoldenError, GoldenSet, load_golden
from .runner import EvalReport, evaluate

__all__ = ["GoldenError", "GoldenSet", "load_golden", "EvalReport", "evaluate"]
