"""Score a generated worksheet against a hand-built reference.

The committed templates (worksheets/doordash-new-verticals.yaml,
worksheets/figma-apm-2027.yaml) are labeled outputs for step 4: the same JD
fed to `resume parse-jd` should recover their requirement set. Matching is
token overlap (the step-2 tokenizer), deliberately forgiving on phrasing and
strict on substance: a reference requirement with no generated counterpart
is a miss whatever the generated file says elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..jd import ParsedJD, Requirement
from ..models import Tier
from ..retrieval import tokenize

MATCH_THRESHOLD = 0.33


@dataclass
class RequirementMatch:
    reference: Requirement
    generated: Requirement | None
    score: float

    @property
    def matched(self) -> bool:
        return self.generated is not None

    @property
    def tier_agrees(self) -> bool:
        return self.matched and self.generated.tier == self.reference.tier


@dataclass
class JDComparison:
    matches: list[RequirementMatch] = field(default_factory=list)
    extra_generated: int = 0
    knockouts_reference: int = 0
    knockouts_generated: int = 0
    signals_generated: int = 0

    @property
    def total(self) -> int:
        return len(self.matches)

    @property
    def covered(self) -> int:
        return sum(1 for m in self.matches if m.matched)

    @property
    def coverage(self) -> float:
        return self.covered / self.total if self.total else 0.0

    @property
    def tier_agreement(self) -> float:
        matched = [m for m in self.matches if m.matched]
        if not matched:
            return 0.0
        return sum(1 for m in matched if m.tier_agrees) / len(matched)

    def by_tier(self) -> dict[Tier, tuple[int, int]]:
        out: dict[Tier, tuple[int, int]] = {}
        for tier in Tier:
            group = [m for m in self.matches if m.reference.tier == tier]
            if group:
                out[tier] = (sum(1 for m in group if m.matched), len(group))
        return out

    def __str__(self) -> str:
        lines = [
            f"coverage       {self.covered}/{self.total} ({self.coverage:.0%}) "
            f"at threshold {MATCH_THRESHOLD}",
        ]
        for tier, (hit, total) in self.by_tier().items():
            lines.append(f"{tier.value:<14} {hit}/{total}")
        lines.append(f"tier agreement {self.tier_agreement:.0%} of matched")
        lines.append(
            f"knockouts      {self.knockouts_generated} generated / "
            f"{self.knockouts_reference} in reference"
        )
        lines.append(
            f"extra          {self.extra_generated} generated requirement(s) with "
            f"no reference counterpart (not necessarily wrong)"
        )
        misses = [m for m in self.matches if not m.matched]
        if misses:
            lines.append("")
            lines.append("missed reference requirements:")
            for m in misses:
                lines.append(f"  ✗ {m.reference.id} [{m.reference.tier.value}] "
                             f"{m.reference.requirement}")
        return "\n".join(lines)


def _score(a: Requirement, b: Requirement) -> float:
    ta, tb = tokenize(a.requirement), tokenize(b.requirement)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def compare(generated: ParsedJD, reference: ParsedJD) -> JDComparison:
    """Match each reference requirement to its best generated counterpart."""
    result = JDComparison(
        knockouts_reference=len(reference.knockouts),
        knockouts_generated=len(generated.knockouts),
        signals_generated=len(generated.signals),
    )
    used: set[str] = set()
    for ref in reference.requirements:
        best, best_score = None, 0.0
        for gen in generated.requirements:
            if gen.id in used:
                continue
            score = _score(ref, gen)
            if score > best_score:
                best, best_score = gen, score
        if best is not None and best_score >= MATCH_THRESHOLD:
            used.add(best.id)
            result.matches.append(RequirementMatch(ref, best, best_score))
        else:
            result.matches.append(RequirementMatch(ref, None, best_score))
    result.extra_generated = len(generated.requirements) - len(used)
    return result
