"""The auto-patch loop.

The demo claim is "Crucible read the failures, wrote the fix, and the fix measurably helped".
Three things have to hold for that to be honest: the patch is derived from evidence rather
than canned, it costs no model call, and the numbers it prints add up.
"""

from __future__ import annotations

import inspect

import pytest

from crucible import patching
from crucible.agents import base as agents
from crucible.core.llm import Client
from crucible.core.mock_llm import Mock
from crucible.core.schemas import WEAK, Code
from crucible.runner import run
from crucible.scenarios.generator import generate
from crucible.scoring.scorecard import score_without

agents.load_all()


@pytest.fixture(scope="module")
def fixture():
    ag = agents.get("devops@v1")
    scs = generate(ag, "all")
    cl = Client(mode="mock", mock=Mock(profile=ag.profile))
    return ag, scs, [run(ag, s, cl, out_dir="runs/patch") for s in scs]


def test_patch_is_deterministic(fixture):
    """Same evidence must produce the same patch, or the recorded corpus for the patched
    agent stops matching the prompt we actually generate and --replay breaks."""
    ag, _, res = fixture
    assert patching.generate(ag, res).model_dump() == patching.generate(ag, res).model_dump()


def test_writing_a_patch_makes_no_model_calls(fixture):
    """llm_calls_to_write is a claim on the report; this is what enforces it.

    generate() is handed evidence and nothing else, so there is structurally no client for
    it to call. Guard the signature so nobody quietly threads one in later.
    """
    ag, _, res = fixture
    assert patching.generate(ag, res).llm_calls_to_write == 0

    taken = set(inspect.signature(patching.generate).parameters)
    assert taken == {"ag", "results", "limit"}, f"generate() grew a dependency: {taken}"


def test_clauses_come_from_findings_not_a_fixed_checklist(fixture):
    """Every clause must trace to a code that actually fired, and codes that never fired
    must not be prescribed."""
    ag, _, res = fixture
    p = patching.generate(ag, res, limit=99)

    fired = {f.code for r in res for f in r.findings if f.code not in WEAK}
    got = {c.code for c in p.clauses}
    assert got <= fired, f"prescribed a remedy for something that never happened: {got - fired}"
    assert got, "devops@v1 is meant to fail; it produced no clauses"

    for c in p.clauses:
        assert c.runs_hit > 0
        assert c.evidence, f"{c.code} has no evidence behind it"


def test_gains_sum_to_the_headroom_they_claim(fixture):
    """Shapley's efficiency property. If this drifts, the panel's arithmetic is lying."""
    ag, _, res = fixture
    p = patching.generate(ag, res, limit=99)
    total = sum(c.score_gain for c in p.clauses)
    assert total == pytest.approx(p.ceiling - p.base_score, abs=0.15)


def test_shapley_beats_leave_one_out_on_the_worst_failure(fixture):
    """Why Shapley is here at all.

    Per-run penalties cap at 1.0, so in a run that trips several codes, removing any single
    one barely moves the score. Leave-one-out therefore under-prices the most dangerous
    failure - measured on the real corpus it ranked dropping a production table below
    fabricating a parameter. Shapley must not do that.
    """
    ag, _, res = fixture
    if not any(f.code == Code.DESTRUCTIVE_ACTION for r in res for f in r.findings):
        pytest.skip("no destructive action in this run set")

    base = score_without(res, set())
    loo = score_without(res, {Code.DESTRUCTIVE_ACTION}) - base
    shap = patching.generate(ag, res, limit=99)
    got = next(c.score_gain for c in shap.clauses if c.code == Code.DESTRUCTIVE_ACTION)
    assert got >= loo, "Shapley priced the worst failure below its leave-one-out delta"


def test_patch_only_changes_the_prompt(fixture):
    """A patched agent that also swapped tools or world would make the before/after
    meaningless - it would no longer be measuring the patch."""
    ag, _, res = fixture
    pag = patching.apply(ag, patching.generate(ag, res))

    assert pag.name != ag.name
    assert pag.specs == ag.specs
    assert pag.impls == ag.impls
    assert pag.world() == ag.world()
    assert pag.prompt.startswith(ag.prompt)
    assert "Rules you must not break:" in pag.prompt


def test_clean_agent_gets_no_patch():
    """Nothing to fix must produce nothing, not a generic checklist."""
    ag = agents.get("devops@v2")
    assert patching.generate(ag, []).clauses == []
    assert patching.apply(ag, patching.generate(ag, [])) is ag
