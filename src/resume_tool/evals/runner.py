"""Run a golden set against a retriever and score it.

Two numbers matter, and they are not the same number:

  - accuracy: is the right experience in the top-k (or the gap flagged)?
  - forced matches: an expected gap answered with a confident candidate.

A forced match is the failure mode this tool exists to prevent — v1 silently
turned missing capabilities into weak bullets — so it is reported separately
and treated as fatal by the CLI, not averaged away into accuracy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .. import retrieval
from ..db import open_db
from ..models import Tier
from .golden import GoldenCase, GoldenSet, build_bank

RetrieveFn = Callable[..., list[retrieval.Candidate]]

DEFAULT_K = 3
DEFAULT_GAP_THRESHOLD = 0.2


@dataclass
class CaseResult:
    case: GoldenCase
    candidates: list[tuple[str, float]]  # (experience ref, score), best first
    predicted_gap: bool
    correct: bool
    rank: int | None  # 1-based rank of the first expected ref, when present

    @property
    def forced_match(self) -> bool:
        return self.case.expects_gap and not self.predicted_gap


@dataclass
class EvalReport:
    golden: GoldenSet
    k: int
    gap_threshold: float
    results: list[CaseResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def correct(self) -> int:
        return sum(1 for r in self.results if r.correct)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def forced_matches(self) -> list[CaseResult]:
        return [r for r in self.results if r.forced_match]

    @property
    def false_gaps(self) -> list[CaseResult]:
        """Cases with a real answer that the retriever called a gap."""
        return [r for r in self.results if not r.case.expects_gap and r.predicted_gap]

    def by_tier(self) -> dict[Tier, tuple[int, int]]:
        out: dict[Tier, tuple[int, int]] = {}
        for tier in Tier:
            results = [r for r in self.results if r.case.tier == tier]
            if results:
                out[tier] = (sum(1 for r in results if r.correct), len(results))
        return out

    def __str__(self) -> str:
        lines = [
            f"Golden set: {self.golden.path} — {self.total} case(s), "
            f"k={self.k}, gap threshold {self.gap_threshold:.2f}",
            "",
        ]
        for r in self.results:
            mark = "✓" if r.correct else "✗"
            requirement = r.case.requirement
            if len(requirement) > 48:
                requirement = requirement[:45] + "..."
            lines.append(
                f"  {mark} {r.case.id:<4} {r.case.tier.value:<12} {requirement:<48} {_outcome(r)}"
            )

        lines.append("")
        lines.append(f"overall       {self.correct}/{self.total} ({self.accuracy:.0%})")
        for tier, (hit, total) in self.by_tier().items():
            lines.append(f"{tier.value:<13} {hit}/{total}")

        expected_gaps = [r for r in self.results if r.case.expects_gap]
        flagged = sum(1 for r in expected_gaps if r.predicted_gap)
        lines.append(
            f"gaps          {flagged}/{len(expected_gaps)} flagged, "
            f"{len(self.false_gaps)} false gap(s), "
            f"{len(self.forced_matches)} forced match(es)"
        )
        if self.forced_matches:
            lines.append("")
            for r in self.forced_matches:
                top = r.candidates[0]
                lines.append(
                    f"  FORCED MATCH {r.case.id}: expected a gap, got "
                    f"{top[0]} ({top[1]:.2f}) — a missing capability would have "
                    f"become a weak bullet"
                )
        return "\n".join(lines)


def _outcome(r: CaseResult) -> str:
    if r.case.expects_gap:
        if r.predicted_gap:
            return "→ gap (correct)"
        top = r.candidates[0]
        return f"→ FORCED {top[0]} ({top[1]:.2f})"
    if r.predicted_gap:
        return f"→ false gap (wanted {', '.join(r.case.expect)})"
    top = r.candidates[0]
    if r.correct:
        return f"→ {top[0]} ({top[1]:.2f}, rank {r.rank})"
    return f"→ {top[0]} ({top[1]:.2f}), wanted {', '.join(r.case.expect)}"


def evaluate(
    golden: GoldenSet,
    retrieve_fn: RetrieveFn = retrieval.retrieve,
    k: int = DEFAULT_K,
    gap_threshold: float = DEFAULT_GAP_THRESHOLD,
) -> EvalReport:
    """Score a retriever against a golden set in a throwaway in-memory bank."""
    conn = open_db(":memory:")
    try:
        ids_by_ref = build_bank(conn, golden)
        ref_by_id = {v: r for r, v in ids_by_ref.items()}

        report = EvalReport(golden=golden, k=k, gap_threshold=gap_threshold)
        for case in golden.cases:
            candidates = retrieve_fn(conn, case.requirement, k)
            predicted_gap = not candidates or candidates[0].score < gap_threshold

            expected_ids = {ids_by_ref[ref] for ref in case.expect}
            rank = next(
                (i + 1 for i, c in enumerate(candidates) if c.experience_id in expected_ids),
                None,
            )
            if case.expects_gap:
                correct = predicted_gap
            else:
                correct = not predicted_gap and rank is not None

            report.results.append(
                CaseResult(
                    case=case,
                    candidates=[
                        (ref_by_id.get(c.experience_id, f"EXP-{c.experience_id}"), c.score)
                        for c in candidates
                    ],
                    predicted_gap=predicted_gap,
                    correct=correct,
                    rank=rank,
                )
            )
        return report
    finally:
        conn.close()
