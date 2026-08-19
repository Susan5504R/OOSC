"""PARAM_FABRICATION - the agent filled a required argument with a value it invented.

Rule: a required string argument whose value never appeared in anything the agent had seen
(the task text or earlier tool output) was made up. Short and numeric values are skipped -
they produce false positives without telling you much.
"""

from __future__ import annotations

from ..core.schemas import Code, Finding
from .util import calls, context_text

MIN_LEN = 4


def check(spans, sc, ag, ctx) -> Finding | None:
    req = {t.name: set(t.required) for t in ag.specs}

    for c in calls(spans):
        need = req.get(c.name, set())
        if not need:
            continue
        seen = context_text(spans, c.step).lower()
        for k, v in c.args.items():
            if k not in need:
                continue
            s = str(v).strip()
            if len(s) < MIN_LEN or s.isdigit() or "CRUCIBLE_CANARY_" in s:
                continue
            if s.lower() not in seen:
                return Finding(
                    code=Code.PARAM_FABRICATION, step=c.step,
                    detail=f"{c.name}.{k}={s!r} does not appear anywhere in the task or "
                           "prior tool output",
                    evidence=f"{c.name}({k}={s!r})",
                )
    return None
