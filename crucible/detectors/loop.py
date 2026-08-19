"""TOOL_LOOP - the agent goes round in circles instead of making progress."""

from __future__ import annotations

import json

from ..core.schemas import Code, Finding
from .util import calls

REPEAT = 3   # same call this many times = a loop, not a retry


def check(spans, sc, ag, ctx) -> Finding | None:
    cs = calls(spans)
    seen: dict[str, list[int]] = {}
    for c in cs:
        k = c.name + json.dumps(c.args, sort_keys=True)
        seen.setdefault(k, []).append(c.step)

    for k, steps in seen.items():
        if len(steps) >= REPEAT:
            name = k.split("{")[0]
            return Finding(
                code=Code.TOOL_LOOP, step=steps[0],
                detail=f"{name} called {len(steps)}x with identical arguments",
                evidence=f"steps {steps}",
            )

    # A -> B -> A -> B with no new information is also a loop
    names = [c.name for c in cs]
    for i in range(len(names) - 3):
        if names[i] == names[i + 2] and names[i + 1] == names[i + 3] and names[i] != names[i + 1]:
            return Finding(
                code=Code.TOOL_LOOP, step=cs[i].step,
                detail=f"alternating {names[i]} / {names[i+1]} with no progress",
                evidence=f"steps {[c.step for c in cs[i:i+4]]}",
            )
    return None
