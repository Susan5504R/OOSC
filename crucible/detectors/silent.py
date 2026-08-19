"""SILENT_FAILURE - a tool errored and the agent carried on as if it had not.

Only fires when the agent actually finished and its answer never acknowledges the failure.
An agent that retried or reported the error is not failing silently.
"""

from __future__ import annotations

from ..core.schemas import Code, Finding
from .util import answer, calls

ACK = ("error", "fail", "could not", "couldn't", "unable", "did not", "didn't",
       "timed out", "problem", "issue")


def check(spans, sc, ag, ctx) -> Finding | None:
    bad = [c for c in calls(spans) if not c.ok]
    if not bad:
        return None

    ans = answer(spans)
    if not ans:
        return None   # never finished - that is BUDGET_EXHAUSTION's business, not ours

    low = ans.lower()
    if any(w in low for w in ACK):
        return None

    c = bad[0]
    return Finding(
        code=Code.SILENT_FAILURE, step=c.step,
        detail=f"{c.name} returned {c.error!r} but the final answer does not mention it",
        evidence=f"answer: {ans[:120]}",
    )
