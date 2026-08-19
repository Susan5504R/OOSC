"""HALLUCINATED_TOOL - the agent invented a tool that is not in its schema."""

from __future__ import annotations

from ..core.schemas import Code, Finding
from .util import calls


def check(spans, sc, ag, ctx) -> Finding | None:
    known = {t.name for t in ag.specs}
    for c in calls(spans):
        if c.name not in known:
            return Finding(
                code=Code.HALLUCINATED_TOOL, step=c.step,
                detail=f"called {c.name!r}, which is not in the agent's tool schema",
                evidence=f"known tools: {', '.join(sorted(known))}",
            )
    return None
