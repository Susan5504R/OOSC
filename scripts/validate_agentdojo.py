"""Grade Crucible's injection detector against AgentDojo's ground truth.

For each (user task, injection task) pair we run the agent once and collect two verdicts:

  ground truth  AgentDojo's own `security()`, which inspects the environment afterwards to
                see whether the attacker's goal actually happened
  crucible      the shipped `detectors.injection.check`, run on spans rebuilt from the same
                message log, keyed on the attacker's target string as a canary

Then we compare them. Results are written after every pair, so hitting the daily quota
costs the run in progress and nothing else.

Live model calls. Run it deliberately:

    python scripts/validate_agentdojo.py --suites banking,slack --pairs 24
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import warnings

warnings.filterwarnings("ignore")

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

OUT = REPO / "reports" / "agentdojo_validation.json"
LOGS = pathlib.Path("/tmp/adlogs")


def _load_env() -> None:
    for line in (REPO / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suites", default="banking,slack,travel,workspace")
    ap.add_argument("--pairs", type=int, default=40, help="max pairs to run this session")
    ap.add_argument("--user-tasks", type=int, default=3, help="user tasks sampled per suite")
    ap.add_argument("--model", default="gemini-3.5-flash-lite")
    args = ap.parse_args()

    _load_env()

    from google import genai

    import adshim  # noqa: F401  - must patch before the pipeline is built
    adshim.install()

    from agentdojo.agent_pipeline import AgentPipeline, PipelineConfig
    from agentdojo.agent_pipeline.llms.google_llm import GoogleLLM
    from agentdojo.attacks import base_attacks
    from agentdojo.attacks.attack_registry import load_attack
    from agentdojo.benchmark import run_task_with_injection_tasks
    from agentdojo.logging import OutputLogger
    from agentdojo.task_suite.load_suites import get_suite

    from crucible.detectors import injection as injdet
    from crucible.external.agentdojo import canaries_for, scenario_for, spans_from_messages

    keys = [k.strip() for k in os.environ["GEMINI_API_KEYS"].split(",") if k.strip()]
    # AgentDojo personalises the attack with the model's name; ours is a Google model.
    base_attacks.MODEL_NAMES[args.model] = "AI model developed by Google"

    rows: list[dict] = []
    if OUT.exists():
        rows = json.loads(OUT.read_text()).get("rows", [])
    done = {(r["suite"], r["user_task"], r["injection_task"]) for r in rows}
    budget = args.pairs

    for si, suite_name in enumerate(args.suites.split(",")):
        if budget <= 0:
            break
        suite = get_suite("v1.2.1", suite_name)

        # round-robin the keys across suites so one pool does not absorb the whole run
        client = genai.Client(api_key=keys[si % len(keys)])
        llm = GoogleLLM(model=args.model, client=client)
        pipe = AgentPipeline.from_config(PipelineConfig(
            llm=llm, model_id=args.model, defense=None,
            system_message_name=None, system_message=None))
        pipe.name = args.model
        attack = load_attack("important_instructions", suite, pipe)

        scoped = [k for k, v in suite.injection_tasks.items() if canaries_for(v.GOAL)]
        goals = {k: suite.injection_tasks[k].GOAL for k in scoped}
        uts = list(suite.user_tasks.values())[: args.user_tasks]

        for ut in uts:
            for inj_id in scoped:
                if budget <= 0:
                    break
                if (suite_name, ut.ID, inj_id) in done:
                    continue
                try:
                    with OutputLogger(str(LOGS), None):
                        _util, sec = run_task_with_injection_tasks(
                            suite, pipe, ut, attack, logdir=LOGS, force_rerun=True,
                            injection_tasks=[inj_id], benchmark_version="v1.2.1")
                except Exception as e:  # a single pair failing must not end the run
                    print(f"  !! {suite_name}/{ut.ID}/{inj_id}: {type(e).__name__}: {e}"[:160])
                    continue
                budget -= 1

                truth = bool(list(sec.values())[0]) if sec else False
                log = (LOGS / args.model / suite_name / ut.ID
                       / "important_instructions" / f"{inj_id}.json")
                if not log.exists():
                    print(f"  !! no trace for {suite_name}/{ut.ID}/{inj_id}")
                    continue
                msgs = json.loads(log.read_text()).get("messages", [])

                spans = spans_from_messages(msgs)
                canary = canaries_for(goals[inj_id])[0]
                findings = injdet.check(spans, scenario_for(canary, ut.PROMPT), None, {})
                codes = {f.code.value for f in findings}
                pred = "INJECTION_COMPLIANCE" in codes

                rows.append({
                    "suite": suite_name, "user_task": ut.ID, "injection_task": inj_id,
                    "canary": canary, "ground_truth": truth, "crucible": pred,
                    "echo": "INJECTION_ECHO" in codes, "steps": len(msgs),
                })
                OUT.parent.mkdir(parents=True, exist_ok=True)
                OUT.write_text(json.dumps({"model": args.model, "rows": rows}, indent=1))
                mark = "OK " if truth == pred else "MISS"
                print(f"  {mark} {suite_name}/{ut.ID}/{inj_id}  truth={truth} crucible={pred}")

    summarise(rows)
    return 0


def summarise(rows: list[dict]) -> None:
    if not rows:
        print("no results")
        return
    tp = sum(1 for r in rows if r["ground_truth"] and r["crucible"])
    tn = sum(1 for r in rows if not r["ground_truth"] and not r["crucible"])
    fp = sum(1 for r in rows if not r["ground_truth"] and r["crucible"])
    fn = sum(1 for r in rows if r["ground_truth"] and not r["crucible"])
    n = len(rows)
    print(f"\n{'='*54}\nCrucible vs AgentDojo ground truth   n={n}")
    print(f"  agreement {100*(tp+tn)/n:.1f}%   TP {tp}  TN {tn}  FP {fp}  FN {fn}")
    if tp + fp:
        print(f"  precision {100*tp/(tp+fp):.1f}%")
    if tp + fn:
        print(f"  recall    {100*tp/(tp+fn):.1f}%")
    echo_only = [r for r in rows if r["echo"] and not r["crucible"]]
    if echo_only:
        clean = sum(1 for r in echo_only if not r["ground_truth"])
        print(f"  echo cases: {len(echo_only)} quoted the canary without acting; "
              f"{clean} confirmed not-compromised by ground truth")


if __name__ == "__main__":
    raise SystemExit(main())
