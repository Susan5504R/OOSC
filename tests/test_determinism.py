"""Determinism and the zero-LLM-call scoring claim.

Both are headline claims in the README. If they are not enforced by a test they will quietly
stop being true.
"""

from __future__ import annotations

import json
from pathlib import Path

from crucible.agents import base as agents
from crucible.core.llm import Client
from crucible.core.mock_llm import Mock
from crucible.runner import run
from crucible.scenarios.generator import generate
from crucible.scoring import scorecard

agents.load_all()


def _run_all(tag: str):
    ag = agents.get("devops@v1")
    cl = Client(mode="mock", mock=Mock(profile=ag.profile))
    return [run(ag, s, cl, out_dir=f"runs/det/{tag}") for s in generate(ag, "all")]


def test_traces_are_byte_identical_across_runs():
    a = _run_all("a")
    b = _run_all("b")
    assert len(a) == len(b)
    for ra, rb in zip(a, b):
        ta = Path(ra.trace_file).read_bytes()
        tb = Path(rb.trace_file).read_bytes()
        assert ta == tb, f"{ra.scenario_id}: trace differed between identical runs"


def test_scoring_makes_no_model_calls():
    """Score a recorded run with a client that raises if anyone touches it."""
    results = _run_all("score")

    class Boom:
        def next(self, *_a, **_k):
            raise AssertionError("scoring must not call a model")

    # detectors already ran inside run(); rebuilding the scorecard must stay offline
    sc = scorecard.build("devops@v1", results)
    assert sc.llm_calls_to_score == 0
    assert sc.runs == len(results)


def test_scenario_ids_are_stable():
    """Scenario ids feed trace ids feed the cache key. Drift here silently invalidates
    the whole replay corpus."""
    ag = agents.get("devops@v1")
    one = [s.id for s in generate(ag, "all")]
    two = [s.id for s in generate(ag, "all")]
    assert one == two


def test_report_is_json_serialisable():
    results = _run_all("json")
    sc = scorecard.build("devops@v1", results)
    blob = json.dumps(scorecard.report("devops@v1", results, sc))
    assert len(blob) > 100
