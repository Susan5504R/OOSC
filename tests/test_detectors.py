"""Each detector fires on the behaviour it is meant to catch, and stays quiet otherwise."""

from __future__ import annotations

import pytest

from crucible.agents import base as agents
from crucible.core.llm import Client
from crucible.core.mock_llm import Mock
from crucible.core.schemas import Code
from crucible.runner import run
from crucible.scenarios.generator import generate
from crucible.scenarios.ladder import NEVER_BROKE
from crucible.scoring import regression, scorecard

agents.load_all()


def _run(agent: str, suite: str, profile: str | None = None):
    ag = agents.get(agent)
    cl = Client(mode="mock", mock=Mock(profile=profile or ag.profile))
    return [run(ag, s, cl, out_dir="runs/test") for s in generate(ag, suite)]


def _codes(results):
    return {f.code for r in results for f in r.findings}


@pytest.mark.parametrize("profile,suite,want", [
    ("looper", "ladder", Code.TOOL_LOOP),
    # a looping agent never reaches a terminal state, so it also runs out of steps
    ("looper", "ladder", Code.BUDGET_EXHAUSTION),
    ("ghost", "ladder", Code.HALLUCINATED_TOOL),
    # needs a suite whose success requires actually doing the work - the ladder only says
    # what the agent must NOT do, which a do-nothing agent satisfies
    ("liar", "adversarial", Code.OVERCONFIDENCE),
    ("liar", "adversarial", Code.GOAL_DRIFT),
    # the adversarial suite injects a FAULTY_TOOL; a fragile agent reports success anyway
    ("fragile", "adversarial", Code.SILENT_FAILURE),
])
def test_profile_trips_its_detector(profile, suite, want):
    assert want in _codes(_run("devops@v1", suite, profile))


def test_param_fabrication_fires():
    """The refund agent needs an order id it was never given, so it invents one."""
    assert Code.PARAM_FABRICATION in _codes(_run("refund@v1", "injection", "fragile"))


def test_doing_nothing_is_not_a_pass():
    """An agent that answers without touching a tool must not score clean."""
    results = _run("devops@v1", "adversarial", "liar")
    assert all(r.failed for r in results)


def test_fragile_agent_drops_the_table_under_pressure():
    got = _codes(_run("devops@v1", "ladder"))
    assert Code.DESTRUCTIVE_ACTION in got
    assert Code.UNSAFE_ESCALATION in got


def test_hardened_agent_holds_the_line():
    got = _codes(_run("devops@v2", "ladder"))
    assert Code.DESTRUCTIVE_ACTION not in got
    assert Code.UNSAFE_ESCALATION not in got


def test_break_point_moves_the_right_way():
    v1 = scorecard.build("devops@v1", _run("devops@v1", "ladder"))
    v2 = scorecard.build("devops@v2", _run("devops@v2", "ladder"))
    assert v1.guardrail_break_point < NEVER_BROKE, "v1 should cave somewhere on the ladder"
    assert v2.guardrail_break_point == NEVER_BROKE, "v2 should hold at every level"
    assert v2.guardrail_break_point > v1.guardrail_break_point


def test_faulty_tool_scenario_is_generated():
    scs = generate(agents.get("devops@v1"), "adversarial")
    assert any(s.faults for s in scs), "no fault-injection scenario generated"


def test_ci_gate_fails_on_regression_and_passes_on_improvement():
    v1 = scorecard.build("devops@v1", _run("devops@v1", "all"))
    v2 = scorecard.build("devops@v2", _run("devops@v2", "all"))

    bad = regression.compare(v2, v1)      # v2 -> v1 is a regression
    assert not bad.ok and bad.reasons

    good = regression.compare(v1, v2)     # v1 -> v2 is an improvement
    assert good.ok, f"unexpected block: {good.reasons}"
    assert good.improvements


def test_v2_scores_higher_than_v1():
    v1 = scorecard.build("devops@v1", _run("devops@v1", "all"))
    v2 = scorecard.build("devops@v2", _run("devops@v2", "all"))
    assert v2.score > v1.score
    assert v2.injection_rate > v1.injection_rate
