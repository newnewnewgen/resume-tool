"""Fit scoring: how well does the bank cover a parsed JD?

The intake qualifier and step 5's matcher. Two layers:

- Keyword retrieval (free, deterministic): ranks experiences per requirement.
  Good at ranking, weak at clearing the gap bar when requirements are
  abstract ("shipped a user-facing launch you can name") and summaries are
  concrete — measured on the first unified run.
- LLM matching (one call per application, optional): classifies each
  requirement strong / weak / gap against the numbered experience list.
  Guarded mechanically: the model may never upgrade a requirement the
  keyword layer found zero shared tokens for — a forced match is the one
  failure this tool exists to prevent, so the guard is code, not prompt.

Scoring a parsed worksheet without the LLM stays free and instant, so a
scan's worth of postings can be ranked without spending anything.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field

from . import retrieval, store
from .jd import ParsedJD, Requirement
from .llm import CompleteFn
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
    llm_strength: str | None = None     # strong | weak | gap, when the LLM pass ran
    llm_overruled: bool = False         # the zero-evidence guard fired

    @property
    def covered(self) -> bool:
        if self.llm_strength is not None:
            return self.llm_strength in ("strong", "weak") and self.best_experience_id is not None
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


def score_fit(
    conn: sqlite3.Connection,
    parsed: ParsedJD,
    k: int = 3,
    complete_fn: CompleteFn | None = None,
) -> FitReport:
    """Score a parsed JD against the bank. Knockouts are excluded: they are
    the user's yes/no, not the bank's. With complete_fn, the LLM match pass
    runs on top of keyword ranking (one call for the whole application)."""
    experiences = store.list_experiences(conn)
    report = FitReport(parsed=parsed, bank_experiences=len(experiences))
    for requirement in parsed.requirements:
        candidates = retrieval.retrieve(conn, _query_text(requirement), k)
        best = candidates[0] if candidates else None
        report.fits.append(RequirementFit(
            requirement=requirement,
            best_experience_id=best.experience_id if best else None,
            best_score=best.score if best else 0.0,
        ))

    if complete_fn is not None and experiences:
        _llm_match(report, experiences, complete_fn, conn)
    return report


MATCH_SYSTEM = """You match job requirements to a candidate's experience \
bank. For each requirement, name the ONE experience that best demonstrates \
it, with a strength:
- "strong": the experience clearly demonstrates the requirement.
- "weak": partial or adjacent evidence — defensible but needs framing.
- "gap": NO experience genuinely demonstrates it. Gaps are a correct and \
expected answer; a missing capability must be reported, never papered over \
with the least-bad experience. When in doubt between weak and gap, answer gap.
For every strong or weak match, "quote" must be a short phrase copied \
VERBATIM, character for character, from that experience's own text — the \
evidence your judgment rests on. A match whose quote is not found verbatim \
in the experience is discarded as a gap, so copy exactly, never paraphrase.
Judge only from the experience text given. Output JSON only — no prose:
[{"id": "R1", "experience": "EXP-003" | null, "strength": "strong|weak|gap",
  "quote": "verbatim phrase from that experience" | null}]"""


def _llm_match(report: FitReport, experiences, complete_fn: CompleteFn, conn) -> None:
    lines = []
    for e in experiences:
        facts = "; ".join(f.value for f in e.facts)
        lines.append(f"{e.display_id}: {e.summary}" + (f" [{facts}]" if facts else ""))
    requirement_lines = [
        f"{f.requirement.id} [{f.requirement.tier.value}]: {f.requirement.requirement} "
        f"(JD evidence: {f.requirement.evidence})"
        for f in report.fits
    ]
    raw = complete_fn(
        MATCH_SYSTEM,
        "EXPERIENCE BANK:\n" + "\n".join(lines)
        + "\n\nREQUIREMENTS:\n" + "\n".join(requirement_lines)
        + "\n\nReturn the JSON array.",
    )
    try:
        data = json.loads(re.sub(r"^```[a-z]*\n|\n```$", "", raw.strip(), flags=re.MULTILINE))
    except json.JSONDecodeError:
        return  # keyword results stand; the pass is an upgrade, not a dependency
    if not isinstance(data, list):
        return

    by_id = {str(item.get("id")): item for item in data if isinstance(item, dict)}
    valid_ids = {e.id for e in experiences}
    for fit in report.fits:
        item = by_id.get(fit.requirement.id)
        if not item:
            continue
        strength = str(item.get("strength") or "").strip().lower()
        if strength not in ("strong", "weak", "gap"):
            continue
        exp_ref = str(item.get("experience") or "")
        match = re.search(r"(\d+)", exp_ref)
        exp_id = int(match.group(1)) if match else None
        if strength == "gap" or exp_id not in valid_ids:
            fit.llm_strength = "gap"
            continue
        # The grounding guard: a claimed match must carry a verbatim quote
        # from the claimed experience. Semantic matches with zero token
        # overlap are legitimate (that is the point of this pass), but an
        # ungrounded claim is not — forced matches stay impossible by
        # construction, not by prompt.
        quote = str(item.get("quote") or "").strip()
        if not quote or not _quote_in_experience(conn, exp_id, quote):
            fit.llm_strength = "gap"
            fit.llm_overruled = True
            continue
        fit.llm_strength = strength
        fit.best_experience_id = exp_id
        fit.best_score = max(
            fit.best_score, _pair_score(conn, fit.requirement, exp_id))


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _quote_in_experience(conn, experience_id: int, quote: str) -> bool:
    experience = store.get_experience(conn, experience_id)
    haystack = _normalize(
        " ".join([experience.summary, *(f.value for f in experience.facts)]))
    return _normalize(quote) in haystack


def _pair_score(conn, requirement: Requirement, experience_id: int) -> float:
    experience = store.get_experience(conn, experience_id)
    return retrieval.score_experience(
        retrieval.tokenize(_query_text(requirement)), experience)


def _query_text(requirement: Requirement) -> str:
    # The evidence quote often carries the JD's concrete nouns (tools, domains)
    # that the distilled requirement text drops; both help retrieval.
    return f"{requirement.requirement} {requirement.evidence}"
