"""Content-addressed cache for model calls.

This is the thing that makes replay work. Key = sha256 over everything that could change
the reply (model, params, full message list, tool schemas). Values are committed to the
repo as the replay corpus, so CI and the hosted demo need no API key at all.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path("traces/cache")


class Miss(Exception):
    """Raised in replay mode. Never fall through to a live call - that would silently
    burn quota and break determinism."""


def key_for(model: str, msgs: list[dict[str, Any]], tools: list[dict[str, Any]], params: dict[str, Any]) -> str:
    blob = json.dumps(
        {"model": model, "msgs": msgs, "tools": tools, "params": params},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


class Cache:
    def __init__(self, root: str | Path = DEFAULT_ROOT):
        self.root = Path(root)

    def _path(self, k: str) -> Path:
        # shard by first two chars, otherwise one flat dir with thousands of files
        return self.root / k[:2] / f"{k}.json"

    def get(self, k: str) -> dict[str, Any] | None:
        p = self._path(k)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def put(self, k: str, val: dict[str, Any]) -> None:
        p = self._path(k)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(val, sort_keys=True, indent=1), encoding="utf-8")

    def has(self, k: str) -> bool:
        return self._path(k).exists()

    def count(self) -> int:
        return sum(1 for _ in self.root.rglob("*.json")) if self.root.exists() else 0
