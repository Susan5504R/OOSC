"""Agent-under-test contract.

An agent is a bundle of (system prompt, tool schema, starting world). The step loop lives
in the runner rather than in each agent - every agent steps identically, they differ only
in what they are told and what they can reach, which is also what makes v1 vs v2 a clean
regression comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..core.schemas import ToolSpec


@dataclass
class Agent:
    name: str                       # "devops@v1"
    prompt: str
    specs: list[ToolSpec]
    world: Callable[[], dict[str, Any]]
    impls: dict[str, Any]
    # which mock_llm profile stands in for this agent under --mock-llm (dev/tests only)
    profile: str = "fragile"
    notes: str = ""
    gated: list[str] = field(default_factory=list)


_REG: dict[str, Agent] = {}


def register(a: Agent) -> Agent:
    _REG[a.name] = a
    return a


def get(name: str) -> Agent:
    if name not in _REG:
        raise KeyError(f"unknown agent {name!r}. known: {', '.join(sorted(_REG))}")
    return _REG[name]


def names() -> list[str]:
    return sorted(_REG)


def load_all() -> None:
    # import for side effects; keeps the CLI from having to know every agent module
    from . import devops_agent, refund_agent  # noqa: F401
