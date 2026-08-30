"""Make AgentDojo's Google adapter work with Gemini 3.x.

AgentDojo was written against Gemini 1.5/2.0, which are retired for new API keys. The
models still reachable are 3.x, and those reject a multi-turn tool conversation unless each
functionCall part is echoed back carrying the `thought_signature` the model issued with it.

AgentDojo drops that signature when it converts a response into its own ChatAssistantMessage,
and never puts it back, so the second turn 400s. This re-attaches it: capture the signature
on the way out, keyed by (function name, args), and restore it on the way back in.

Nothing here changes what the agent does or how AgentDojo scores it - it only keeps the
conversation well-formed for a newer API.
"""

from __future__ import annotations

import json

from google.genai import types as genai_types

from agentdojo.agent_pipeline.llms import google_llm as g

_SIGS: dict[tuple[str, str], bytes] = {}


def _key(name: str | None, args) -> tuple[str, str]:
    return (name or "", json.dumps(dict(args or {}), sort_keys=True, default=str))


_orig_to_assistant = g._google_to_assistant_message


def _to_assistant(message: genai_types.GenerateContentResponse):
    try:
        for part in message.candidates[0].content.parts or []:
            sig = getattr(part, "thought_signature", None)
            if part.function_call is not None and sig:
                _SIGS[_key(part.function_call.name, part.function_call.args)] = sig
    except (AttributeError, IndexError, TypeError):
        pass
    return _orig_to_assistant(message)


def _parts_from_assistant_message(assistant_message) -> list[genai_types.Part]:
    parts = []
    if assistant_message["content"] is not None:
        for part in assistant_message["content"]:
            parts.append(genai_types.Part.from_text(text=part["content"]))
    for tc in assistant_message["tool_calls"] or []:
        p = genai_types.Part.from_function_call(name=tc.function, args=dict(tc.args))
        sig = _SIGS.get(_key(tc.function, tc.args))
        if sig:
            p.thought_signature = sig
        parts.append(p)
    return parts


def install() -> None:
    g._google_to_assistant_message = _to_assistant
    g._parts_from_assistant_message = _parts_from_assistant_message
    # _message_to_google closed over the original at import time, so rebind there too
    if hasattr(g, "_message_to_google"):
        g._message_to_google.__globals__["_parts_from_assistant_message"] = _parts_from_assistant_message
