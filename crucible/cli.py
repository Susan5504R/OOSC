"""crucible - CI for autonomous agents.

  crucible agents                          list agents under test
  crucible gen    --agent devops@v1        show generated scenarios
  crucible run    --agent devops@v1        run a suite and score it
  crucible report                          export dashboard JSON
  crucible ci --base devops@v2 --head devops@v1    regression gate
  crucible corpus --agent devops@v1        record the replay corpus (LIVE, spends quota)

Default mode is --mock-llm: zero network, zero quota.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .agents import base as agents
from .core.cache import Cache
from .core.llm import Client
from .core.mock_llm import Mock
from .runner import run as run_one
from .scenarios.generator import generate
from .scoring import regression, scorecard

app = typer.Typer(add_completion=False, help=__doc__)
con = Console()

REPORTS = Path("reports")


def _client(mode: str, ag) -> Client:
    if mode == "mock":
        return Client(mode="mock", mock=Mock(profile=ag.profile))
    return Client(mode=mode, cache=Cache())


def _mode(mock: bool, replay: bool, live: bool) -> str:
    if sum([mock, replay, live]) > 1:
        raise typer.BadParameter("pick one of --mock-llm / --replay / --live")
    if replay:
        return "replay"
    if live:
        return "live"
    return "mock"


@app.command()
def agents_list() -> None:
    """List agents under test."""
    agents.load_all()
    t = Table("agent", "profile", "gated tools", "notes")
    for n in agents.names():
        a = agents.get(n)
        t.add_row(n, a.profile, ", ".join(a.gated) or "-", a.notes)
    con.print(t)


@app.command("gen")
def gen(agent: str = typer.Option(..., "--agent"),
        suite: str = typer.Option("all", "--suite")) -> None:
    """Show the scenarios generated from an agent's tool schema."""
    agents.load_all()
    ag = agents.get(agent)
    scs = generate(ag, suite)
    t = Table("id", "suite", "L", "mutators", "task")
    for s in scs:
        t.add_row(s.id, s.suite, str(s.pressure),
                  ",".join(m.value[:4] for m in s.mutators) or "-",
                  s.task[:70] + ("..." if len(s.task) > 70 else ""))
    con.print(t)
    con.print(f"[dim]{len(scs)} scenarios, generated from {len(ag.specs)} tool schemas, "
              f"0 API calls[/dim]")


@app.command()
def run(agent: str = typer.Option(..., "--agent"),
        suite: str = typer.Option("all", "--suite"),
        mock_llm: bool = typer.Option(True, "--mock-llm/--no-mock-llm"),
        replay: bool = typer.Option(False, "--replay"),
        live: bool = typer.Option(False, "--live"),
        out: str = typer.Option("reports", "--out")) -> None:
    """Run a suite against an agent and score it."""
    agents.load_all()
    ag = agents.get(agent)
    mode = _mode(mock_llm and not replay and not live, replay, live)
    cl = _client(mode, ag)

    scs = generate(ag, suite)
    results = [run_one(ag, s, cl) for s in scs]
    sc = scorecard.build(ag.name, results)

    Path(out).mkdir(parents=True, exist_ok=True)
    p = Path(out) / f"{ag.name.replace('@', '_')}.json"
    p.write_text(json.dumps(scorecard.report(ag.name, results, sc), indent=1))

    _show(sc, results, mode)
    con.print(f"[dim]report -> {p}[/dim]")


def _show(sc, results, mode: str) -> None:
    con.print()
    con.print(f"[bold]{sc.agent}[/bold]  score [bold]{sc.score}[/bold]/100   "
              f"pass {sc.pass_rate:.0%}   runs {sc.runs}   [dim]mode={mode}[/dim]")
    con.print(f"guardrail break point: [bold]{sc.break_label}[/bold]")
    if sc.injection_resistance:
        con.print(f"injection resistance: {sc.injection_rate:.0%} "
                  f"({sum(sc.injection_resistance.values())}/{len(sc.injection_resistance)} "
                  "payload classes)")

    if sc.failures:
        t = Table("failure mode", "runs", "rate")
        for k, v in sc.failures.items():
            t.add_row(k, str(v), f"{sc.failure_rates[k]:.0%}")
        con.print(t)
    con.print(f"[green]scored with {sc.llm_calls_to_score} LLM calls[/green]")


@app.command()
def ci(base: str = typer.Option(..., "--base"),
       head: str = typer.Option(..., "--head"),
       suite: str = typer.Option("all", "--suite"),
       replay: bool = typer.Option(False, "--replay")) -> None:
    """Regression gate. Exits 1 when head is worse than base."""
    agents.load_all()
    mode = "replay" if replay else "mock"

    cards = {}
    for name in (base, head):
        ag = agents.get(name)
        cl = _client(mode, ag)
        res = [run_one(ag, s, cl) for s in generate(ag, suite)]
        cards[name] = scorecard.build(name, res)

    v = regression.compare(cards[base], cards[head])
    con.print(f"[bold]base[/bold] {base} {v.base_score}   "
              f"[bold]head[/bold] {head} {v.head_score}   delta {v.delta:+}")
    for g in v.improvements:
        con.print(f"  [green]+[/green] {g}")
    for r in v.reasons:
        con.print(f"  [red]-[/red] {r}")

    if v.ok:
        con.print("[green]PASS[/green] no reliability regression")
        raise typer.Exit(0)
    con.print("[red]FAIL[/red] reliability regression - blocking")
    raise typer.Exit(1)


@app.command()
def report(out: str = typer.Option("web/public/data", "--out")) -> None:
    """Collect reports/*.json into the static bundle the dashboard reads."""
    Path(out).mkdir(parents=True, exist_ok=True)
    files = sorted(REPORTS.glob("*.json"))
    if not files:
        con.print("[red]no reports yet - run `crucible run` first[/red]")
        raise typer.Exit(1)

    bundle = {"agents": []}
    for f in files:
        d = json.loads(f.read_text())
        bundle["agents"].append(d)
    Path(out, "report.json").write_text(json.dumps(bundle, indent=1))
    con.print(f"bundled {len(files)} agent reports -> {out}/report.json")


@app.command()
def corpus(agent: str = typer.Option(..., "--agent"),
           suite: str = typer.Option("all", "--suite")) -> None:
    """Record the replay corpus against the live model. Spends daily quota - run once.

    Needs `pip install -r requirements-live.txt` and GEMINI_API_KEYS in the environment
    (see .env.example). Fails fast with a plain message if either is missing, rather than
    a raw traceback - this is meant to be run by hand, by whoever holds the API key.
    """
    try:
        import google.genai  # noqa: F401
    except ImportError:
        con.print("[red]google-genai is not installed.[/red] "
                  "Run: pip install -r requirements-live.txt")
        raise typer.Exit(1)
    if not (os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY")):
        con.print("[red]No GEMINI_API_KEYS set.[/red] "
                  "Copy .env.example to .env and fill in a real key, then `source .env` "
                  "or export it before running this command.")
        raise typer.Exit(1)

    agents.load_all()
    ag = agents.get(agent)
    cl = Client(mode="live", cache=Cache())
    scs = generate(ag, suite)
    con.print(f"[yellow]LIVE[/yellow] {len(scs)} scenarios for {ag.name} "
              f"(cache hits cost nothing; only misses call the API)")
    try:
        for s in scs:
            run_one(ag, s, cl)
            con.print(f"  {s.id} {s.suite} done  [dim]live calls so far: {cl.live_calls}[/dim]")
    except RuntimeError as e:
        con.print(f"[red]stopped: {e}[/red]")
        con.print(f"[dim]cache entries written before the stop: {Cache().count()} "
                  "(nothing is lost - rerun the same command to resume)[/dim]")
        raise typer.Exit(1)
    con.print(f"[green]corpus updated[/green] live calls: {cl.live_calls}, "
              f"cache entries: {Cache().count()}")


if __name__ == "__main__":
    app()
