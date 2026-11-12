"""Fit scoring: how well does the bank cover a parsed JD?

The intake qualifier. Where career-ops scores a job against a CV with a
generic LLM rubric, this scores it against the fact bank deterministically:
every requirement is retrieved against the user's own experiences, and the
score is coverage — weighted toward the critical tier, with the gaps named.
The same mechanics are step 5's first half; intake is just step 5 run before
the user has committed to applying.

Zero LLM calls: scoring a parsed worksheet is free and instant, so a scan's
worth of postings can be ranked without spending anything.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from . import retrieval, store
from .jd import ParsedJD, Requirement
from .models import Tier

# Tier weights: a critical gap should cost roughly three times an important
# one, and nice-to-haves are nearly free (matching the worksheet doctrine:
# report-and-skip).
TIER_WEIGHTS = {Tier.CRITICAL: 3.0, Tier.IMPORTANT: 1.0, Tier.NICE_TO_HAVE: 0.25}

# Retrieval score at or above which a requirement counts as covered. Matches
# the eval harness's gap threshold so intake and step 5 agree on what a gap is.
COVER_THRESHOLD = 0.2

# Verdict cutoffs on the weighted coverage score (0..1).
APPLY_AT = 0.65
STRETCH_AT = 0.40


@dataclass
class RequirementFit:
    requirement: Requirement
    best_experience_id: int | None
    best_score: float

    @property
    def covered(self) -> bool:
        return self.best_experience_id is not None and self.best_score >= COVER_THRESHOLD


@dataclass
class FitReport:
    parsed: ParsedJD
    fits: list[RequirementFit] = field(default_factory=list)
    bank_experiences: int = 0

    @property
    def weighted_score(self) -> float:
        total = sum(TIER_WEIGHTS[f.requirement.tier] for f in self.fits)
        if not total:
            return 0.0
        covered = sum(TIER_WEIGHTS[f.requirement.tier] for f in self.fits if f.covered)
        return covered / total

    @property
    def verdict(self) -> str:
        if not self.bank_experiences:
            return "NO BANK"
        if self.weighted_score >= APPLY_AT:
            return "APPLY"
        if self.weighted_score >= STRETCH_AT:
            return "STRETCH"
        return "SKIP"

    def coverage_by_tier(self) -> dict[Tier, tuple[int, int]]:
        out: dict[Tier, tuple[int, int]] = {}
        for tier in Tier:
            group = [f for f in self.fits if f.requirement.tier == tier]
            if group:
                out[tier] = (sum(1 for f in group if f.covered), len(group))
        return out

    def gaps(self, tier: Tier | None = None) -> list[RequirementFit]:
        return [
            f for f in self.fits
            if not f.covered and (tier is None or f.requirement.tier == tier)
        ]

    def __str__(self) -> str:
        p = self.parsed
        lines = [
            f"{p.company} — {p.role_title}",
            f"verdict        {self.verdict}  (weighted coverage "
            f"{self.weighted_score:.0%}, bank of {self.bank_experiences})",
        ]
        for tier, (hit, total) in self.coverage_by_tier().items():
            lines.append(f"{tier.value:<14} {hit}/{total}")
        critical_gaps = self.gaps(Tier.CRITICAL)
        if critical_gaps:
            lines.append("")
            lines.append("critical gaps (fill with a real story, or accept):")
            for f in critical_gaps:
                lines.append(f"  ✗ {f.requirement.id}  {f.requirement.requirement}")
        other_gaps = [f for f in self.gaps() if f.requirement.tier != Tier.CRITICAL]
        if other_gaps:
            lines.append("")
            lines.append("other gaps (report-and-skip):")
            for f in other_gaps:
                lines.append(
                    f"  - {f.requirement.id} [{f.requirement.tier.value}] "
                    f"{f.requirement.requirement}"
                )
        return "\n".join(lines)


def score_fit(conn: sqlite3.Connection, parsed: ParsedJD, k: int = 3) -> FitReport:
    """Score a parsed JD against the bank. Knockouts are excluded: they are
    the user's yes/no, not the bank's."""
    report = FitReport(parsed=parsed, bank_experiences=len(store.list_experiences(conn)))
    for requirement in parsed.requirements:
        candidates = retrieval.retrieve(conn, _query_text(requirement), k)
        best = candidates[0] if candidates else None
        report.fits.append(RequirementFit(
            requirement=requirement,
            best_experience_id=best.experience_id if best else None,
            best_score=best.score if best else 0.0,
        ))
    return report


def _query_text(requirement: Requirement) -> str:
    # The evidence quote often carries the JD's concrete nouns (tools, domains)
    # that the distilled requirement text drops; both help retrieval.
    return f"{requirement.requirement} {requirement.evidence}"
