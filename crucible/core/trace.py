"""Append-only JSONL trace of OTel-shaped spans.

One file per run. Deterministic replay diffs these byte-for-byte, so nothing
non-reproducible (wall clock, random ids, absolute paths) may leak into a span unless it
came from the recorded run itself.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterator

from .schemas import Span, SpanEvent


def _hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def trace_id_for(*parts: str) -> str:
    """Trace ids are derived from run identity, never random.

    A random id would differ on every replay and break the byte-identical diff that the
    whole determinism claim rests on.
    """
    return _hash(*parts)[:32]


class Clock:
    """Monotonic fake clock.

    Real timestamps would make replayed traces differ on every run, which kills the
    byte-identical guarantee. Spans get a deterministic counter instead; real elapsed time
    is not something we score on.
    """

    def __init__(self, start: int = 0):
        self.t = start

    def tick(self, n: int = 1_000_000) -> int:
        self.t += n
        return self.t


class Writer:
    def __init__(self, path: str | Path, trace_id: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.trace_id = trace_id
        self.clock = Clock()
        self.spans: list[Span] = []
        self.n = 0
        self._fh = self.path.open("w", encoding="utf-8")

    def _next_id(self) -> str:
        self.n += 1
        return _hash(self.trace_id, str(self.n))[:16]

    def span(
        self,
        name: str,
        attrs: dict[str, Any] | None = None,
        parent: str | None = None,
        events: list[SpanEvent] | None = None,
        status: str = "OK",
    ) -> Span:
        start = self.clock.tick()
        end = self.clock.tick()
        s = Span(
            trace_id=self.trace_id,
            span_id=self._next_id(),
            parent_span_id=parent,
            name=name,
            start_unix_nano=start,
            end_unix_nano=end,
            attributes=attrs or {},
            events=events or [],
            status=status,
        )
        self.spans.append(s)
        self._fh.write(json.dumps(s.model_dump(), sort_keys=True) + "\n")
        self._fh.flush()
        return s

    def event(self, name: str, **attrs: Any) -> SpanEvent:
        return SpanEvent(name=name, time_unix_nano=self.clock.tick(), attributes=attrs)

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> "Writer":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def read(path: str | Path) -> list[Span]:
    out: list[Span] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(Span.model_validate_json(line))
    return out


def tool_calls(spans: list[Span]) -> Iterator[Span]:
    """Every span where the agent actually invoked a tool, in order."""
    for s in spans:
        if s.name == "tool.call":
            yield s


# replay writes go to the same tree as live runs; keep the layout in one place
def run_dir(root: str | os.PathLike[str], agent: str, suite: str) -> Path:
    p = Path(root) / agent.replace("@", "_") / suite
    p.mkdir(parents=True, exist_ok=True)
    return p
