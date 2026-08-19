"""Model adapter with three modes: mock, replay, live.

mock   - scripted fake model, zero network. The default for development.
replay - cache only. A miss raises; it must never fall through to a live call.
live   - real Gemini, wrapped in cache + rate limit + daily budget. Used once, to build
         the replay corpus.

google-genai is imported lazily so mock/replay (and CI) work without it installed.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .cache import Cache, Miss, key_for
from .schemas import ToolCall, ToolSpec

BUDGET_FILE = Path(".crucible_budget.json")


class Reply(BaseModel):
    text: str = ""
    call: ToolCall | None = None
    cached: bool = True


# --------------------------------------------------------------- wire protocol
# We use a plain text protocol instead of provider function-calling: it keeps the adapter
# provider-agnostic, parses deterministically, and holds up better on the cheap models we
# deliberately run the agents-under-test on.

PROTO = """When you act, reply with exactly one line:
TOOL: <tool_name> <json args>
When you are finished, reply with exactly one line:
DONE: <your answer>
No other output."""

_TOOL_RE = re.compile(r"^\s*TOOL:\s*([A-Za-z_][A-Za-z0-9_]*)\s*(\{.*\})?\s*$", re.S | re.M)
_DONE_RE = re.compile(r"^\s*DONE:\s*(.*)$", re.S | re.M)


def parse(text: str) -> Reply:
    m = _TOOL_RE.search(text)
    if m:
        args: dict[str, Any] = {}
        if m.group(2):
            try:
                args = json.loads(m.group(2))
            except json.JSONDecodeError:
                # malformed args are themselves a signal - keep the raw string so
                # PARAM_FABRICATION / HALLUCINATED_TOOL can still see what happened
                args = {"_raw": m.group(2)}
        return Reply(text=text, call=ToolCall(name=m.group(1), args=args))

    d = _DONE_RE.search(text)
    if d:
        return Reply(text=d.group(1).strip())
    # no recognisable action - treat the whole thing as a final answer
    return Reply(text=text.strip())


def tools_blob(tools: list[ToolSpec]) -> str:
    out = []
    for t in tools:
        ps = ", ".join(f"{k}: {v}" for k, v in t.params.items()) or "none"
        out.append(f"- {t.name}({ps}) - {t.desc}")
    return "\n".join(out)


# --------------------------------------------------------------- budget / limits

class Budget:
    """Daily call counter, persisted so a restart can't reset it.

    Free-tier RPD is what actually kills this project - RPM you can wait out, a burned
    daily quota costs a full day.
    """

    def __init__(self, cap: int, path: Path = BUDGET_FILE):
        self.cap = cap
        self.path = path

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except json.JSONDecodeError:
            return {}

    def spend(self, n: int = 1) -> int:
        day = time.strftime("%Y-%m-%d")
        d = self._load()
        used = d.get(day, 0) + n
        if used > self.cap:
            raise RuntimeError(
                f"daily live-call budget exhausted ({used}/{self.cap}). "
                "Use --mock-llm or --replay; do not raise the cap without thinking."
            )
        d[day] = used
        self.path.write_text(json.dumps(d))
        return used


class Bucket:
    """Dead simple token bucket. Free tier is per-minute, so seconds-level pacing is enough."""

    def __init__(self, per_min: int):
        self.gap = 60.0 / max(per_min, 1)
        self.last = 0.0

    def wait(self) -> None:
        dt = time.time() - self.last
        if dt < self.gap:
            time.sleep(self.gap - dt)
        self.last = time.time()


# --------------------------------------------------------------- client

class Client:
    def __init__(
        self,
        mode: str = "mock",
        model: str | None = None,
        cache: Cache | None = None,
        mock: Any = None,
        per_min: int = 8,
        daily_cap: int | None = None,
    ):
        self.mode = mode
        self.model = model or os.getenv("CRUCIBLE_AGENT_MODEL", "gemini-3.5-flash-lite")
        self.cache = cache or Cache()
        self.mock = mock
        self.calls = 0
        self.live_calls = 0
        self.bucket = Bucket(per_min)
        cap = daily_cap if daily_cap is not None else int(os.getenv("CRUCIBLE_DAILY_CALL_BUDGET", "150"))
        self.budget = Budget(cap)
        self._keys: list[str] = []
        self._ki = 0

    # -------------------------------------------------- public

    def complete(self, msgs: list[dict[str, str]], tools: list[ToolSpec]) -> Reply:
        self.calls += 1
        if self.mode == "mock":
            return self.mock.next(msgs, tools)

        tspec = [t.model_dump() for t in tools]
        k = key_for(self.model, msgs, tspec, {"temperature": 0})

        hit = self.cache.get(k)
        if hit is not None:
            r = parse(hit["text"])
            r.cached = True
            return r

        if self.mode == "replay":
            raise Miss(
                f"cache miss in replay mode (key {k[:12]}). The corpus does not cover this "
                "run. Regenerate it with `crucible corpus`, do not silently go live."
            )

        text = self._live(msgs, tools)
        self.cache.put(k, {"text": text, "model": self.model})
        r = parse(text)
        r.cached = False
        return r

    # -------------------------------------------------- live

    def _load_keys(self) -> list[str]:
        raw = os.getenv("GEMINI_API_KEYS", "") or os.getenv("GEMINI_API_KEY", "")
        keys = [k.strip() for k in raw.split(",") if k.strip()]
        if not keys:
            raise RuntimeError("no GEMINI_API_KEYS set - live mode needs at least one key")
        return keys

    def _next_key(self) -> str:
        # round-robin across accounts: two keys = two separate free-tier quota pools
        if not self._keys:
            self._keys = self._load_keys()
        k = self._keys[self._ki % len(self._keys)]
        self._ki += 1
        return k

    def _live(self, msgs: list[dict[str, str]], tools: list[ToolSpec]) -> str:
        from google import genai  # lazy: mock/replay must not need this installed
        from google.genai import types

        self.budget.spend()
        self.bucket.wait()
        self.live_calls += 1

        sys = "\n".join(m["content"] for m in msgs if m["role"] == "system")
        convo = [m for m in msgs if m["role"] != "system"]
        text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in convo)

        last_err: Exception | None = None
        for attempt in range(4):
            try:
                cl = genai.Client(api_key=self._next_key())
                resp = cl.models.generate_content(
                    model=self.model,
                    contents=text,
                    config=types.GenerateContentConfig(
                        system_instruction=sys,
                        temperature=0,
                        max_output_tokens=400,
                    ),
                )
                return resp.text or ""
            except Exception as e:  # 429s and transient 5xx both land here
                last_err = e
                if "429" not in str(e) and "RESOURCE_EXHAUSTED" not in str(e).upper():
                    raise
                time.sleep(2 ** attempt * 2)
        raise RuntimeError(f"live call failed after retries: {last_err}")
