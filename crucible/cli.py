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

from . import patching
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


def _patched(ag, scs):
    """The auto-patched variant of `ag`, derived from its own cached results.

    The patch is deterministic, so this costs nothing to recompute and lands on the same
    prompt every time - which is what lets the patched corpus be recorded once and replayed.
    """
    rcl = Client(mode="replay", cache=Cache())
    p = patching.generate(ag, [run_one(ag, s, rcl) for s in scs])
    if not p.clauses:
        con.print(f"[red]{ag.name} has no patchable findings - nothing to patch.[/red]")
        raise typer.Exit(1)
    return patching.apply(ag, p), p


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
        patched: bool = typer.Option(False, "--patched"),
        out: str = typer.Option("reports", "--out")) -> None:
    """Run a suite against an agent and score it.

    --patched scores the auto-patched variant instead, against the very same scenarios, so
    the before/after is measuring the patch and nothing else.
    """
    agents.load_all()
    ag = agents.get(agent)
    mode = _mode(mock_llm and not replay and not live, replay, live)

    scs = generate(ag, suite)
    if patched:
        ag, _ = _patched(ag, scs)
    cl = _client(mode, ag)
    results = [run_one(ag, s, cl) for s in scs]
    sc = scorecard.build(ag.name, results)

    Path(out).mkdir(parents=True, exist_ok=True)
    p = Path(out) / f"{ag.name.replace('@', '_')}.json"
    rep = scorecard.report(ag.name, results, sc)
    # free: the patch is derived from findings we already have, with no model call
    rep["patch"] = patching.generate(ag, results).model_dump()
    p.write_text(json.dumps(rep, indent=1))

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


@app.command("patch")
def patch_cmd(agent: str = typer.Option(..., "--agent"),
              suite: str = typer.Option("all", "--suite"),
              mock_llm: bool = typer.Option(True, "--mock-llm/--no-mock-llm"),
              replay: bool = typer.Option(False, "--replay"),
              live: bool = typer.Option(False, "--live"),
              verify: bool = typer.Option(False, "--verify"),
              limit: int = typer.Option(6, "--limit")) -> None:
    """Write a system-prompt patch from what actually broke. --verify proves it works.

    Crucible already classifies how an agent failed. This turns those findings into the
    rules that would have prevented them, ranked by what fixing each one is worth, and then
    re-runs the patched agent against the very same scenarios to measure whether it helped.
    """
    agents.load_all()
    ag = agents.get(agent)
    mode = _mode(mock_llm and not replay and not live, replay, live)

    scs = generate(ag, suite)
    cl = _client(mode, ag)
    before = [run_one(ag, s, cl) for s in scs]
    p = patching.generate(ag, before, limit=limit)

    if not p.clauses:
        con.print(f"[green]{ag.name} tripped no patchable failure mode - nothing to fix.[/green]")
        raise typer.Exit(0)

    t = Table("failure mode", "worth", "runs hit", "evidence")
    for c in p.clauses:
        t.add_row(c.code.value, f"+{c.score_gain}", f"{c.runs_hit}/{len(before)}",
                  (c.evidence[0][:58] + "...") if c.evidence else "-")
    con.print(t)
    con.print(f"[dim]worth = Shapley share of the {round(p.ceiling - p.base_score, 1)} points "
              f"between the measured {p.base_score} and the {p.ceiling} ceiling. "
              "The ceiling assumes every one of these stops firing - it is a bound, not a "
              "forecast.[/dim]\n")
    con.print("[bold]generated patch[/bold] [dim](append to the system prompt)[/dim]")
    con.print(f"[cyan]{p.block}[/cyan]")
    con.print(f"[green]written with {p.llm_calls_to_write} LLM calls[/green]")

    if not verify:
        con.print("\n[dim]re-run with --verify to measure whether it actually helps[/dim]")
        raise typer.Exit(0)

    # Same scenario objects, not a regenerated suite: only the prompt may differ, otherwise
    # the before/after would not be measuring the patch.
    pag = patching.apply(ag, p)
    pcl = _client(mode, pag)
    after = [run_one(pag, s, pcl) for s in scs]
    a, b = scorecard.build(ag.name, before), scorecard.build(pag.name, after)

    con.print()
    v = Table("", "score", "pass", "break point", "injection")
    for lbl, card in (("before", a), ("after", b)):
        v.add_row(f"{lbl}  {card.agent}", f"{card.score}", f"{card.pass_rate:.0%}",
                  card.break_label,
                  f"{sum(card.injection_resistance.values())}/{len(card.injection_resistance)}"
                  if card.injection_resistance else "-")
    con.print(v)

    d = round(b.score - a.score, 1)
    tone = "green" if d > 0 else "red"
    con.print(f"[{tone}]{'+' if d > 0 else ''}{d} points[/{tone}] measured, "
              f"against a {round(p.ceiling - p.base_score, 1)}-point ceiling "
              f"[dim](mode={mode})[/dim]")


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
           suite: str = typer.Option("all", "--suite"),
           patched: bool = typer.Option(False, "--patched")) -> None:
    """Record the replay corpus against the live model. Spends daily quota - run once.

    --patched records the auto-patched variant instead. The patch is derived from the base
    agent's already-cached results, so it costs nothing to regenerate and is identical every
    time; only the patched agent's own runs hit the API.

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

    if patched:
        # same scenarios as the base agent, so the before/after stays like-for-like
        ag, p = _patched(ag, scs)
        con.print(f"[dim]patched variant: {ag.name} ({len(p.clauses)} clauses)[/dim]")

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
