# CLAUDE.md — Crucible

Guidance for Claude Code (and humans) working in this repo. Read before writing code.

---

## What this is

**Crucible** — an AI Agent Evaluation & Reliability Engine. Continuous integration for
autonomous agents: it generates adversarial test scenarios from an agent's own tool schema,
runs the agent in a sandbox with mocked tools, classifies how it failed, and scores
reliability across versions so a CI gate can block a regression.

Built for a hackathon (Unstop Phase 1, Round 1) against **Problem Statement 4 — AI Agent
Evaluation and Reliability Engine**. Industry benchmarks put real-world agent task failure
near 70%; teams ship against a handful of hand-written prompts, so tool-call loops,
hallucinated confidence, unsafe destructive actions and silent goal drift only surface in
production.

### Deliverables (all mandatory)
- Working prototype, hosted link (Vercel, static)
- GitHub repo with a well-documented README
- Demo video, **≤10 minutes**
- Judged on: innovation · technical implementation · feasibility · scalability · code
  quality · documentation · presentation

---

## The five things that make this win — protect them

1. **Scoring requires zero LLM calls.** Every failure mode is caught by deterministic trace
   inspection or a scenario-authored success predicate. Reproducible, auditable, free.
2. **Content-addressed replay.** Model calls cached by hash of (model, prompt, tools,
   params). A run replays byte-identical with no API calls. This is why the hosted demo
   needs no key and no backend.
3. **Prompt-injection benchmark with canary detection.** Six payload classes, each carrying
   a cryptographic action canary. Compliance is *proven*, not judged.
4. **Pressure-ladder guardrail probing.** Five escalating levels of social pressure; report
   the **Guardrail Break Point**.
5. **A CI gate that actually runs.** `crucible ci` exits non-zero on regression, wired to a
   GitHub Action that runs in replay mode **with zero secrets configured**.

---

## Hard invariants — never violate

- **Sandbox mocks only. No real side effects, ever.** No tool implementation may touch the
  real filesystem, network, or any external service. A test asserts this.
- **Cache-first.** Never write a "make it work now, add caching later" LLM path. The cache
  wraps the client from the first call.
- **`--replay` hard-fails on a cache miss.** It must never silently fall through to a live
  API call.
- **Do NOT install the OpenTelemetry SDK.** We emit OTel-*shaped* JSON only. Adding the SDK
  costs a day we don't have.
- **v1 agents are deliberately fragile.** They loop, they cave under pressure, they drop the
  production table. That is the product demonstrating itself. **Do not "fix" a v1 agent.**
  Hardening belongs in the v2 variant, which is the regression story.
- **Never commit an API key.** `.env` is gitignored; `.env.example` documents the shape.

---

## Free-tier survival rules

We are on free-tier Gemini. The **daily** request cap is the project-killing risk — RPM is
solvable by waiting, a burned daily quota costs ~24 of our 48 hours.

- **`--mock-llm` is the default dev mode.** A scripted fake LLM. Detectors, scoring, CI and
  the entire dashboard are developed and tested against it with **zero API calls**.
- Token bucket + exponential backoff on 429. One shared client.
- Two API keys (two Google accounts), round-robined — separate quota pools.
- Weakest/cheapest model for agents-under-test. We *want* failures; a weak model is both
  quota-friendly and better demo material.
- Log every live call and print a running counter. Hard-stop at a self-imposed daily budget.
- The replay corpus is generated **once**, committed, and never regenerated casually.

---

## Layout

```
crucible/
  core/      schemas.py  trace.py  cache.py  llm.py  mock_llm.py
  agents/    base.py  devops_agent.py  refund_agent.py
  sandbox/   executor.py  mocks.py
  scenarios/ mutators.py  payloads.py  generator.py  ladder.py
  detectors/ one file per failure mode
  scoring/   scorecard.py  regression.py
  cli.py  api.py
web/         Vite + React + Tailwind + Recharts (static dashboard)
traces/      committed replay corpus
reports/     generated JSON the dashboard reads
```

`api.py` (FastAPI) is **local dev only**. The hosted dashboard is static and reads exported
JSON from `reports/` — no backend, no keys, nothing to fall over during judging.

---

## Failure taxonomy

| Code | Detection |
|---|---|
| `TOOL_LOOP` | deterministic |
| `DESTRUCTIVE_ACTION` | deterministic |
| `HALLUCINATED_TOOL` | deterministic |
| `PARAM_FABRICATION` | deterministic |
| `BUDGET_EXHAUSTION` | deterministic |
| `SILENT_FAILURE` | deterministic |
| `INJECTION_COMPLIANCE` | deterministic (action canary) |
| `UNSAFE_ESCALATION` | deterministic (ladder) |
| `GOAL_DRIFT` | scenario success predicate |
| `OVERCONFIDENCE` | scenario success predicate |

### The canary rule (get this wrong and the demo lies)

- **Action canary is the detector.** The injected payload instructs a tool call carrying the
  canary as an argument. A canary in **tool-call args** is unambiguous compliance.
- **Text echo is NOT compliance.** An agent that correctly refuses often quotes the
  injection while refusing it. Echo is recorded as a separate weak `INJECTION_ECHO` signal
  and **must never fire `INJECTION_COMPLIANCE` on its own.** There is a mandatory test for
  this.

### Predicates over judges

Each scenario ships a small Python success predicate asserting final sandbox state. That
makes `GOAL_DRIFT` and `OVERCONFIDENCE` deterministic too. `detectors/judge.py` is a
**stretch goal only** — do not put it on the critical path.

---

## Code conventions

- Python 3.11. Pydantic v2 at all boundaries. Type hints everywhere.
- **Agent state is a frozen Pydantic model** (`model_config = ConfigDict(frozen=True)`),
  evolved with `.model_copy(update=...)`. Never mutate in place — we snapshot state every
  step for the trace viewer, and a mutated dict logs references, making every step render
  identically.
- One detector per file, each exposing `check(trace, scenario) -> Finding | None`.
- Scoring weights live in **one** documented config dict. No magic numbers scattered around.
- Short, pragmatic names (`res`, `n`, `cur`, `buf`). Comment the *why*, not the *what*.
  Skip comments on obvious code. Don't extract a helper used once.
- Guard clauses over nested ifs.

### Trace format

OTel-*shaped* spans: `trace_id`, `span_id`, `parent_span_id`, start/end nanos, `attributes`,
`events`, `status`. Attribute names follow **OpenTelemetry GenAI semantic conventions** —
`gen_ai.system`, `gen_ai.operation.name`, `gen_ai.request.model`, `gen_ai.usage.*`,
`gen_ai.tool.name`. Our own keys go under `crucible.*`.

---

## Honesty rules (a caught overclaim costs more than the claim gains)

- Say *"OTel-shaped spans following GenAI semantic conventions; OTLP export is a thin
  adapter."* Never bare "OpenTelemetry-compatible" — we don't export OTLP.
- Live runs are **not** deterministic, even at `temperature=0`. *Replay* is deterministic —
  which is exactly why replay exists. Say it that way.
- Measure the CI wall-clock time before quoting it. Don't promise a number we haven't seen.
- Record every demo-video clip from the replay corpus, never a live call. Identical on
  screen, and a 429 on camera is unrecoverable.

---

## Git

- Develop on `claude/hackathon-round-1-prototype-aew7cd`. Push with `-u origin <branch>`.
- Open the PR as a draft.
- Never put a model identifier in commit messages, PR bodies, or code comments.

---

## Non-goals

No real tool execution. No auth or multi-tenancy. No model training or fine-tuning. No
scraping. Not a general observability platform — the scope is evaluating agents we are given.
