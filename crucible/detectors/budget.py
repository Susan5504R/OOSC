"""BUDGET_EXHAUSTION - hit the step cap without ever reaching a terminal state."""

from __future__ import annotations

from ..core.schemas import Code, Finding
from .util import end


def check(spans, sc, ag, ctx) -> Finding | None:
    e = end(spans)
    if not e.get("crucible.hit_step_cap"):
        return None
    return Finding(
        code=Code.BUDGET_EXHAUSTION, step=int(e.get("crucible.steps", 0)),
        detail=f"ran out of steps ({sc.max_steps}) without producing an answer",
        evidence=f"steps={e.get('crucible.steps')}",
    )
