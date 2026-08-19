"""The hard invariant: tools never touch anything real.

A prototype that evaluates destructive agents must not itself be capable of destruction.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from crucible.sandbox import mocks
from crucible.sandbox.executor import DockerExecutor, MockExecutor

# modules whose use inside a tool implementation would mean real side effects
BANNED = {"os", "subprocess", "shutil", "socket", "requests", "urllib", "httpx", "pathlib"}


def test_tool_impls_import_nothing_dangerous():
    src = pathlib.Path(mocks.__file__).read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[0] not in BANNED, f"mocks.py imports {a.name}"
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in BANNED, f"mocks.py imports {node.module}"


def test_tools_only_mutate_the_passed_dict():
    w = mocks.devops_world()
    before = sorted(w["tables"])
    mocks.DEVOPS_IMPLS["drop_table"](w, {"table": "events"})
    assert "events" not in w["tables"]
    # a fresh world is untouched - nothing global was mutated
    assert sorted(mocks.devops_world()["tables"]) == before


def test_snapshot_is_a_copy_not_a_reference():
    """The trace must hold values. A reference would make every step render identically."""
    from crucible.agents.devops_agent import SPECS

    ex = MockExecutor(mocks.devops_world(), mocks.DEVOPS_IMPLS, SPECS)
    snap = ex.snapshot()
    ex.world["tables"].remove("events")
    assert "events" in snap["tables"], "snapshot aliased live state"


def test_docker_executor_is_an_unbuilt_placeholder():
    """It documents the scale-out path; it must never silently pretend to work."""
    with pytest.raises(NotImplementedError):
        DockerExecutor()


def test_unknown_tool_is_refused_not_executed():
    from crucible.agents.devops_agent import SPECS
    from crucible.core.schemas import ToolCall

    ex = MockExecutor(mocks.devops_world(), mocks.DEVOPS_IMPLS, SPECS)
    res = ex.call(ToolCall(name="rm_rf", args={"path": "/"}))
    assert not res.ok and res.error == "no_such_tool"
