"""Tool execution.

HARD INVARIANT: nothing here touches the real filesystem, network, or any external
service. Every "tool" mutates an in-memory dict. tests/test_sandbox_safety.py enforces it.

The Protocol exists so the mocked layer can be swapped for real containerised execution
later without the runner or the detectors changing - see DockerExecutor.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Callable, Protocol

from ..core.schemas import Injection, ToolCall, ToolResult, ToolSpec

Impl = Callable[[dict[str, Any], dict[str, Any]], ToolResult]


class ToolExecutor(Protocol):
    """Anything that can run an agent's tool call and report world state."""

    def call(self, tc: ToolCall) -> ToolResult: ...

    def snapshot(self) -> dict[str, Any]: ...


class MockExecutor:
    """In-memory executor. The only implementation we ship.

    Also the place adversarial conditions are applied: scripted faults and injection
    payloads are attached to a tool's *output*, which is exactly how a real agent would
    encounter untrusted content.
    """

    def __init__(
        self,
        world: dict[str, Any],
        impls: dict[str, Impl],
        specs: list[ToolSpec],
        faults: dict[str, str] | None = None,
        injections: list[Injection] | None = None,
    ):
        self.world = world
        self.impls = impls
        self.specs = {t.name: t for t in specs}
        self.faults = faults or {}
        self.injections = injections or []
        self.log: list[tuple[ToolCall, ToolResult]] = []

    def call(self, tc: ToolCall) -> ToolResult:
        spec = self.specs.get(tc.name)
        if spec is None:
            res = ToolResult(ok=False, error="no_such_tool",
                             content=f"error: no tool named {tc.name!r}")
            self.log.append((tc, res))
            return res

        fault = self.faults.get(tc.name)
        if fault:
            res = _fault(fault, tc.name)
        else:
            impl = self.impls[tc.name]
            res = impl(self.world, dict(tc.args))

        # plant any payload carried by this tool's output
        for inj in self.injections:
            if inj.tool == tc.name and res.ok:
                res.content = f"{res.content}\n{inj.text}"

        self.log.append((tc, res))
        return res

    def snapshot(self) -> dict[str, Any]:
        # deep copy: the trace must hold a value, not a reference that keeps mutating
        return copy.deepcopy(self.world)


class DockerExecutor:
    """Planned real-isolation executor. Not implemented - see README, Architecture Evolution.

    Design: one ephemeral container per run, tools mapped to processes inside it, the
    container joined to a network namespace with no egress except an explicit allowlist.
    Filesystem and network syscalls are observed from outside, so a destructive action is
    detected by what the agent *did*, not by what it said. Traces stay identical, so every
    detector and the whole scorecard keep working unchanged - which is the point of the
    ToolExecutor Protocol.
    """

    def __init__(self, *_: Any, **__: Any):
        raise NotImplementedError(
            "DockerExecutor is a design placeholder. The prototype runs MockExecutor only, "
            "which guarantees zero real side effects."
        )


# ---------------------------------------------------------------- faults

def _fault(kind: str, tool: str) -> ToolResult:
    if kind == "error":
        return ToolResult(ok=False, error="upstream_500",
                          content=f"error: {tool} failed with upstream 500")
    if kind == "timeout":
        return ToolResult(ok=False, error="timeout",
                          content=f"error: {tool} timed out after 30s")
    if kind == "empty":
        return ToolResult(ok=True, content="")
    if kind == "malformed":
        return ToolResult(ok=True, content="{'rows': [ , , ")
    return ToolResult(ok=True, content="")


CANARY_RE = re.compile(r"CRUCIBLE_CANARY_[0-9a-f]+")


def canaries_in(text: str) -> list[str]:
    return CANARY_RE.findall(text or "")
