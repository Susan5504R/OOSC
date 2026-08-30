"""Generate a system-prompt patch from what actually broke.

Crucible already says how an agent failed. This closes the loop: read the findings, pick the
remedy for each failure mode that really fired, rank them by what fixing them is worth, and
emit a prompt block you can paste straight into the agent.

Two things keep this honest:

- Ranking is a Shapley value, not a heuristic, and not leave-one-out. Per-run penalties are
  capped at 1.0, so once a run trips two or three failure modes the cap saturates and
  removing any single one of them barely moves the score. Naive leave-one-out therefore
  prices the *most* dangerous failure lowest - measured here, dropping a production table
  came out below fabricating a parameter, which is nonsense. Shapley averages each code's
  marginal contribution over every subset of the others, which is the standard fix for
  attribution under a saturating function, and it makes the per-clause gains sum exactly to
  the total headroom. There are at most ten codes, so the 2^n subset walk is instant.
- `ceiling` is labelled a ceiling, not a prediction. It is what the agent would score if
  every patched failure mode stopped firing completely. Real prompts do not work that well.
  The number that matters is the one you get by re-running the patched agent, which is what
  `crucible patch --verify` does.

No model call anywhere in here, same as scoring.
"""

from __future__ import annotations

from dataclasses import replace
from itertools import combinations
from math import factorial

from pydantic import BaseModel, Field

from ..agents.base import Agent, register
from ..core.schemas import WEAK, Code, RunResult
from ..scoring.scorecard import score_without
from .clauses import clause_for

PATCH_SUFFIX = "+patch"


class Clause(BaseModel):
    code: Code
    text: str
    runs_hit: int
    rate: float
    # Shapley-attributed share of the headroom between base_score and ceiling
    score_gain: float
    evidence: list[str] = Field(default_factory=list)


class Patch(BaseModel):
    agent: str
    base_score: float
    # upper bound: every patched code stops firing. Not a prediction - see module docstring.
    ceiling: float
    clauses: list[Clause] = Field(default_factory=list)
    # always 0, same as llm_calls_to_score: the claim is computed, not asserted
    llm_calls_to_write: int = 0

    @property
    def block(self) -> str:
        """The patch as it gets appended to the agent's system prompt."""
        if not self.clauses:
            return ""
        lines = "\n".join(f"- {c.text}" for c in self.clauses)
        return f"Rules you must not break:\n{lines}"


def _where(r: RunResult) -> str:
    if r.suite == "ladder":
        return f"ladder L{r.pressure}"
    if r.suite == "injection" and r.payload_cls is not None:
        return f"injection {r.payload_cls.value}"
    return f"{r.suite} {r.scenario_id[:6]}"


def shapley(results: list[RunResult], codes: list[Code]) -> dict[Code, float]:
    """Split the total achievable score gain across `codes` by Shapley value.

    v(S) is what the run set gains if every code in S stops firing. Because v saturates,
    order matters, so each code is credited with its average marginal contribution over all
    subsets of the others. Memoised on the subset, so v runs at most 2^n times.
    """
    order = sorted(codes, key=lambda c: c.value)
    n = len(order)
    if not n:
        return {}

    base = score_without(results, set())
    seen: dict[frozenset[Code], float] = {}

    def v(s: frozenset[Code]) -> float:
        if s not in seen:
            seen[s] = score_without(results, set(s)) - base
        return seen[s]

    out: dict[Code, float] = {}
    for c in order:
        rest = [x for x in order if x != c]
        total = 0.0
        for k in range(n):
            w = factorial(k) * factorial(n - k - 1) / factorial(n)
            for sub in combinations(rest, k):
                s = frozenset(sub)
                total += w * (v(s | {c}) - v(s))
        out[c] = round(total, 1)
    return out


def generate(ag: Agent, results: list[RunResult], limit: int = 6) -> Patch:
    """Build the patch for `ag` from its own run results."""
    base = score_without(results, set())

    fired: dict[Code, list[RunResult]] = {}
    for r in results:
        for c in {f.code for f in r.findings if f.code not in WEAK}:
            fired.setdefault(c, []).append(r)

    # only price codes we can actually write a remedy for
    priced = [c for c in fired if clause_for(ag, c)]

    # Two passes. The first ranks every code so a truncated patch still keeps the clauses
    # that matter most; the second re-splits over just the kept ones, so the reported gains
    # sum to exactly the ceiling this patch actually reaches rather than to the ceiling of
    # a longer patch we did not emit.
    first = shapley(results, priced)
    ranked = sorted(priced, key=lambda c: (-first.get(c, 0.0), -len(fired[c]), c.value))
    kept = ranked[:limit]
    gains = shapley(results, kept)

    clauses = []
    for code in kept:
        hits = fired[code]
        ev = [f"{_where(r)}: {f.detail}"
              for r in hits[:3] for f in r.findings if f.code == code][:3]
        clauses.append(Clause(
            code=code,
            text=clause_for(ag, code) or "",
            runs_hit=len(hits),
            rate=round(len(hits) / len(results), 3) if results else 0.0,
            score_gain=gains.get(code, 0.0),
            evidence=ev,
        ))
    clauses.sort(key=lambda c: (-c.score_gain, -c.rate, c.code.value))

    return Patch(
        agent=ag.name,
        base_score=base,
        ceiling=score_without(results, set(kept)),
        clauses=clauses,
    )


def apply(ag: Agent, patch: Patch) -> Agent:
    """A patched copy of the agent, registered so the runner and CLI can reach it by name.

    Only the prompt changes. Same tools, same world, same everything else - otherwise the
    before/after comparison would not be measuring the patch.
    """
    if not patch.clauses:
        return ag
    out = replace(
        ag,
        name=f"{ag.name}{PATCH_SUFFIX}",
        prompt=f"{ag.prompt}\n\n{patch.block}",
        profile="hardened",
        notes=f"auto-patched from {len(patch.clauses)} failure modes found in {ag.name}",
    )
    return register(out)
