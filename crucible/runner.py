"""Run one agent against one scenario, in the sandbox, recording an OTel-shaped trace."""

from __future__ import annotations

import json
from pathlib import Path

from .agents.base import Agent
from .core import trace
from .core.llm import PROTO, Client, tools_blob
from .core.schemas import RunResult, Scenario, Step, ToolCall
from .detectors import run_all
from .sandbox.executor import MockExecutor


def _system(ag: Agent) -> str:
    return f"{ag.prompt}\n\nTools available:\n{tools_blob(ag.specs)}\n\n{PROTO}"


def run(ag: Agent, sc: Scenario, cl: Client, out_dir: str | Path = "runs") -> RunResult:
    ex = MockExecutor(
        world=ag.world(),
        impls=ag.impls,
        specs=ag.specs,
        faults=sc.faults,
        injections=sc.injections,
    )

    tid = trace.trace_id_for(ag.name, sc.id)
    path = Path(out_dir) / ag.name.replace("@", "_") / sc.suite / f"{sc.id}.jsonl"
    w = trace.Writer(path, trace_id=tid)

    msgs = [{"role": "system", "content": _system(ag)},
            {"role": "user", "content": sc.task}]

    root = w.span("run", {
        "crucible.agent": ag.name,
        "crucible.scenario": sc.id,
        "crucible.suite": sc.suite,
        "crucible.pressure": sc.pressure,
        "crucible.mutators": [m.value for m in sc.mutators],
        "crucible.task": sc.task,
    })

    calls: list[ToolCall] = []
    detail: list[Step] = []
    answer = ""
    step = 0

    while step < sc.max_steps:
        step += 1
        r = cl.complete(msgs, ag.specs)

        w.span("llm.call", {
            "gen_ai.system": "crucible",
            "gen_ai.operation.name": "chat",
            "gen_ai.request.model": cl.model,
            "gen_ai.request.temperature": 0,
            "crucible.step": step,
            "crucible.cached": r.cached,
            "crucible.reply": r.text,
        }, parent=root.span_id)

        if r.call is None:
            answer = r.text
            msgs.append({"role": "assistant", "content": r.text})
            detail.append(Step(n=step, reply=r.text[:400], world=ex.snapshot()))
            break

        msgs.append({"role": "assistant", "content": r.text})
        calls.append(r.call)
        res = ex.call(r.call)
        detail.append(Step(n=step, reply=r.text[:400], tool=r.call.name, args=r.call.args,
                           ok=res.ok, result=res.content[:400], world=ex.snapshot()))

        w.span("tool.call", {
            "gen_ai.tool.name": r.call.name,
            "crucible.step": step,
            "crucible.tool.args": json.dumps(r.call.args, sort_keys=True),
            "crucible.tool.ok": res.ok,
            "crucible.tool.error": res.error or "",
            "crucible.tool.content": res.content,
            "crucible.world": ex.snapshot(),
        }, parent=root.span_id, status="OK" if res.ok else "ERROR")

        msgs.append({"role": "tool", "content": res.content})

    w.span("run.end", {
        "crucible.steps": step,
        "crucible.answer": answer,
        "crucible.hit_step_cap": step >= sc.max_steps and not answer,
        "crucible.world_final": ex.snapshot(),
    }, parent=root.span_id)
    w.close()

    ctx = {"world": ex.world, "calls": calls, "answer": answer}
    findings = run_all(w.spans, sc, ag, ctx)

    flagged = {f.step for f in findings if f.step is not None}
    for d in detail:
        d.flagged = d.n in flagged

    return RunResult(
        run_id=tid[:12],
        scenario_id=sc.id,
        agent=ag.name,
        suite=sc.suite,
        pressure=sc.pressure,
        steps=step,
        findings=findings,
        trace_file=str(path),
        llm_calls=cl.calls,
        payload_cls=sc.injections[0].cls if sc.injections else None,
        task=sc.task,
        steps_detail=detail,
    )
