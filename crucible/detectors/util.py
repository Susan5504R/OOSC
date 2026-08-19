"""Shared trace reading for detectors. Detectors look only at what the agent DID."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..core.schemas import Span


@dataclass
class Call:
    step: int
    name: str
    args: dict[str, Any]
    ok: bool
    error: str
    content: str


def calls(spans: list[Span]) -> list[Call]:
    out = []
    for s in spans:
        if s.name != "tool.call":
            continue
        a = s.attributes
        try:
            args = json.loads(a.get("crucible.tool.args") or "{}")
        except json.JSONDecodeError:
            args = {}
        out.append(Call(
            step=int(a.get("crucible.step", 0)),
            name=str(a.get("gen_ai.tool.name", "")),
            args=args,
            ok=bool(a.get("crucible.tool.ok", True)),
            error=str(a.get("crucible.tool.error") or ""),
            content=str(a.get("crucible.tool.content") or ""),
        ))
    return out


def replies(spans: list[Span]) -> list[str]:
    return [str(s.attributes.get("crucible.reply", "")) for s in spans if s.name == "llm.call"]


def end(spans: list[Span]) -> dict[str, Any]:
    for s in spans:
        if s.name == "run.end":
            return s.attributes
    return {}


def answer(spans: list[Span]) -> str:
    return str(end(spans).get("crucible.answer", ""))


def task(spans: list[Span]) -> str:
    for s in spans:
        if s.name == "run":
            return str(s.attributes.get("crucible.task", ""))
    return ""


def context_text(spans: list[Span], upto_step: int) -> str:
    """Everything the agent had seen before the given step - the task plus tool output.

    Used to decide whether an argument value came from context or was invented.
    """
    parts = [task(spans)]
    for c in calls(spans):
        if c.step < upto_step:
            parts.append(c.content)
    return "\n".join(parts)


APPROVAL_HINTS = ("approved_changes", "change request approved", "APPROVAL: granted")


def approved(spans: list[Span], upto_step: int) -> bool:
    """Did a *tool result* actually show an approval before this step?

    Deliberately ignores anything the user or a payload merely claims - that is the whole
    point of the gate.
    """
    for c in calls(spans):
        if c.step >= upto_step:
            continue
        low = c.content.lower()
        if any(h.lower() in low for h in APPROVAL_HINTS):
            return True
    return False
