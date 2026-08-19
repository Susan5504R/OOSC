"""Failure detectors.

Every detector here is deterministic: it reads the recorded trace and the scenario's own
success predicates, and makes no model call. Scoring a run costs zero tokens, which is what
makes the CI gate free to run on every pull request.

detectors/judge.py (an LLM second opinion) is deliberately NOT on this list. It is a
stretch goal - nothing in the scorecard depends on it.
"""

from __future__ import annotations

from ..core.schemas import Finding
from . import budget, destructive, fabrication, goal, halluc, injection, loop, silent

# order matters only for how findings are listed in the report
MODULES = [destructive, injection, loop, halluc, fabrication, silent, budget, goal]


def run_all(spans, sc, ag, ctx) -> list[Finding]:
    out: list[Finding] = []
    for m in MODULES:
        r = m.check(spans, sc, ag, ctx)
        if r is None:
            continue
        out.extend(r if isinstance(r, list) else [r])
    return out
