"""Local dev API. NOT used by the hosted dashboard - that reads static JSON.

This exists so a live run can be triggered from a browser during development without
shelling out to the CLI. It is never deployed; Vercel serves web/dist as a static site.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .agents import base as agents
from .core.cache import Cache
from .core.llm import Client
from .core.mock_llm import Mock
from .runner import run as run_one
from .scenarios.generator import generate
from .scoring import scorecard

agents.load_all()

app = FastAPI(title="crucible-dev-api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/agents")
def list_agents() -> list[str]:
    return agents.names()


@app.get("/run/{agent}")
def run(agent: str, suite: str = "all", mode: str = "mock") -> dict:
    try:
        ag = agents.get(agent)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e

    if mode not in ("mock", "replay"):
        raise HTTPException(400, "mode must be 'mock' or 'replay' - live runs are CLI-only")

    cl = Client(mode="mock", mock=Mock(profile=ag.profile)) if mode == "mock" \
        else Client(mode="replay", cache=Cache())

    results = [run_one(ag, s, cl) for s in generate(ag, suite)]
    sc = scorecard.build(ag.name, results)
    return scorecard.report(ag.name, results, sc)
