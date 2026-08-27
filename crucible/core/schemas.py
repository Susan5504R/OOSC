"""Shared data model. Everything that crosses a module boundary is defined here."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------- tools

class ToolSpec(BaseModel):
    """What an agent-under-test exposes. Scenario generation reads these directly."""
    name: str
    desc: str
    params: dict[str, str] = Field(default_factory=dict)   # param -> short type/desc
    required: list[str] = Field(default_factory=list)
    # irreversible in the real world (drop a table, move money, delete a file)
    destructive: bool = False
    # must see an explicit human/system approval before firing
    needs_confirm: bool = False


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    ok: bool = True
    content: str = ""
    error: str | None = None


# ---------------------------------------------------------------- agent state

class Msg(BaseModel):
    model_config = ConfigDict(frozen=True)
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    # set when role == "assistant" and the model asked for a tool
    call: ToolCall | None = None


class AgentState(BaseModel):
    """Frozen on purpose.

    We snapshot state into the trace on every step. If this were mutable the trace would
    hold references and the viewer would render the final state at every step, making the
    agent look like it did nothing. Evolve with .model_copy(update=...).
    """
    model_config = ConfigDict(frozen=True)

    msgs: tuple[Msg, ...] = ()
    step: int = 0
    done: bool = False
    answer: str = ""

    def add(self, *ms: Msg) -> AgentState:
        return self.model_copy(update={"msgs": self.msgs + ms, "step": self.step + 1})

    def finish(self, text: str) -> AgentState:
        return self.model_copy(update={"done": True, "answer": text})


# ---------------------------------------------------------------- scenarios

class Mutator(str, Enum):
    AMBIGUITY = "AMBIGUITY"
    CONTRADICTION = "CONTRADICTION"
    AUTHORITY_PRESSURE = "AUTHORITY_PRESSURE"
    URGENCY = "URGENCY"
    INJECTED_TOOL_OUTPUT = "INJECTED_TOOL_OUTPUT"
    DISTRACTOR = "DISTRACTOR"
    FAULTY_TOOL = "FAULTY_TOOL"
    SCOPE_CREEP = "SCOPE_CREEP"
    IMPERSONATION = "IMPERSONATION"


class PayloadClass(str, Enum):
    DIRECT_OVERRIDE = "DIRECT_OVERRIDE"
    FAKE_SYSTEM = "FAKE_SYSTEM"
    FORGED_AUTH = "FORGED_AUTH"
    DEFERRED = "DEFERRED"
    OBFUSCATED = "OBFUSCATED"
    EMBEDDED_DATA = "EMBEDDED_DATA"


class Injection(BaseModel):
    """One injection payload planted in a mocked tool's output."""
    cls: PayloadClass
    tool: str          # which tool's output carries it
    canary: str        # CRUCIBLE_CANARY_xxxx
    text: str          # the payload as it appears in the tool result
    # the tool the payload tries to get called with the canary as an arg
    lure_tool: str
    lure_arg: str


class Predicate(BaseModel):
    """Declarative success check. Evaluated against final world state + the trace.

    Declarative (not a lambda) so it serialises into the report and stays deterministic.
    Registered kinds live in scenarios/predicates.py.
    """
    kind: str
    args: dict[str, Any] = Field(default_factory=dict)


class Scenario(BaseModel):
    id: str
    agent: str                      # "devops@v1"
    task: str                       # the user request as the agent sees it
    mutators: list[Mutator] = Field(default_factory=list)
    pressure: int = 0               # 0..4, see scenarios/ladder.py
    injections: list[Injection] = Field(default_factory=list)
    success: list[Predicate] = Field(default_factory=list)
    # tools the agent must not fire without approval, for UNSAFE_ESCALATION
    gated: list[str] = Field(default_factory=list)
    max_steps: int = 8
    # scripted faults: tool name -> how the mock should misbehave
    faults: dict[str, str] = Field(default_factory=dict)
    suite: str = "default"


# ---------------------------------------------------------------- trace (OTel-shaped)

class SpanEvent(BaseModel):
    name: str
    time_unix_nano: int
    attributes: dict[str, Any] = Field(default_factory=dict)


class Span(BaseModel):
    """OTel-SHAPED span. We deliberately do not depend on the OpenTelemetry SDK.

    Attribute keys follow the OTel GenAI semantic conventions (gen_ai.*) where one applies;
    everything Crucible-specific is namespaced crucible.*.
    """
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    name: str
    start_unix_nano: int
    end_unix_nano: int
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[SpanEvent] = Field(default_factory=list)
    status: Literal["OK", "ERROR"] = "OK"


# ---------------------------------------------------------------- findings / results

class Code(str, Enum):
    TOOL_LOOP = "TOOL_LOOP"
    DESTRUCTIVE_ACTION = "DESTRUCTIVE_ACTION"
    HALLUCINATED_TOOL = "HALLUCINATED_TOOL"
    PARAM_FABRICATION = "PARAM_FABRICATION"
    BUDGET_EXHAUSTION = "BUDGET_EXHAUSTION"
    SILENT_FAILURE = "SILENT_FAILURE"
    INJECTION_COMPLIANCE = "INJECTION_COMPLIANCE"
    UNSAFE_ESCALATION = "UNSAFE_ESCALATION"
    GOAL_DRIFT = "GOAL_DRIFT"
    OVERCONFIDENCE = "OVERCONFIDENCE"
    # weak signal only - never counted as a failure, see the canary rule in CLAUDE.md
    INJECTION_ECHO = "INJECTION_ECHO"


# INJECTION_ECHO is diagnostic. A correctly-refusing agent quotes the payload while
# refusing it; counting that as a breach would mark our best agent as compromised.
WEAK = {Code.INJECTION_ECHO}


class Finding(BaseModel):
    code: Code
    detail: str
    step: int | None = None
    # what in the trace proves it - shown in the dashboard next to the finding
    evidence: str = ""

    @property
    def weak(self) -> bool:
        return self.code in WEAK


class Step(BaseModel):
    """Compact per-step record for the dashboard's trace viewer.

    The full OTel spans live in the .jsonl trace; this is the trimmed view so the static
    bundle the dashboard downloads stays small.
    """
    n: int
    reply: str = ""
    tool: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    ok: bool = True
    result: str = ""
    flagged: bool = False       # a finding points at this step
    # sandbox state as it stands AFTER this step. Small (~160 bytes) and it is what lets the
    # replay view show a table actually disappearing rather than just naming the tool call.
    world: dict[str, Any] = Field(default_factory=dict)


class RunResult(BaseModel):
    run_id: str
    scenario_id: str
    agent: str
    suite: str = "default"
    pressure: int = 0
    steps: int = 0
    findings: list[Finding] = Field(default_factory=list)
    trace_file: str = ""
    llm_calls: int = 0
    # injection bookkeeping, used for the resistance-rate chart
    payload_cls: PayloadClass | None = None
    task: str = ""
    steps_detail: list[Step] = Field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(not f.weak for f in self.findings)
