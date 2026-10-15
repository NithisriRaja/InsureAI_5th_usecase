"""Turn messy model text into JSON, and Pydantic models into provider-friendly JSON Schema."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from pydantic import BaseModel

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json(text: str) -> Any:
    """Parse JSON from model output that may include reasoning tags, fences or prose.

    Raises ValueError when no JSON object can be found.
    """
    cleaned = _THINK.sub("", text or "").strip()
    candidates = [m.group(1).strip() for m in _FENCE.finditer(cleaned)] + [cleaned]
    for cand in candidates:
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            pass
        obj = _first_balanced_object(cand)
        if obj is not None:
            try:
                return json.loads(obj)
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON object found in model output")


def _first_balanced_object(s: str) -> str | None:
    start = s.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(s)):
            ch = s[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return s[start : i + 1]
        start = s.find("{", start + 1)
    return None


# Keywords many structured-output backends reject; bounds are enforced by Pydantic anyway.
_STRIP_KEYS = {
    "title",
    "default",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "pattern",
    "format",
    "examples",
}


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Inline $refs, require every property, forbid extras, drop unsupported keywords."""
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                return walk(copy.deepcopy(defs[name]))
            out = {k: walk(v) for k, v in node.items() if k not in _STRIP_KEYS}
            if out.get("type") == "object" and "properties" in out:
                out["required"] = list(out["properties"])
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(raw)


def schema_prompt(model: type[BaseModel]) -> str:
    return json.dumps(strict_schema(model), indent=None, separators=(",", ":"))
