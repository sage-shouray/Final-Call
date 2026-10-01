"""Per-tenant payload shaping.

Every customer runs their own SAP, and their Z-endpoints expect different JSON:
different key names, different nesting, different wrappers. Hard-coding one
shape meant onboarding a customer required a code change.

An admin now pastes that customer's sample JSON with placeholders where the
document data belongs, and this module fills it in. The template is data, so a
new customer is a configuration task rather than a deployment.

Syntax
------
    "{{po_number}}"            a whole-string placeholder — substituted and
                               left as its native type, so numbers stay numbers
    "PO-{{po_number}}"         embedded in text — substituted as a string
    "{{header.company_code}}"  dotted paths walk nested context
    [{"__repeat__": "line_items", "item": "{{item.po_item}}"}]
                               an array whose single object carries __repeat__
                               is expanded once per element of that list, with
                               `item` bound to each element

Anything without placeholders is emitted verbatim, so constants the customer
requires (tax indicators, plant codes) live in the template rather than in code.
"""
from __future__ import annotations

import re
from typing import Any

import structlog

log = structlog.get_logger(__name__)

_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")
_WHOLE = re.compile(r"^\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}$")

REPEAT_KEY = "__repeat__"
ITEM_BINDING = "item"


class TemplateError(ValueError):
    """Raised when a template cannot be rendered against the given context."""


def _lookup(path: str, context: dict[str, Any]) -> Any:
    """Resolve a dotted path, returning None when any segment is absent.

    Missing resolves to None rather than raising: a customer template may
    reference a field their SAP wants but this document does not carry, and that
    should produce an explicit null rather than fail the whole posting.
    """
    current: Any = context
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current


def _render_string(value: str, context: dict[str, Any], missing: list[str]) -> Any:
    whole = _WHOLE.match(value.strip())
    if whole:
        # The entire string is one placeholder, so preserve the value's type —
        # SAP rejects "1000.00" where it expects a number.
        resolved = _lookup(whole.group(1), context)
        if resolved is None:
            missing.append(whole.group(1))
        return resolved

    def _sub(match: re.Match[str]) -> str:
        resolved = _lookup(match.group(1), context)
        if resolved is None:
            missing.append(match.group(1))
            return ""
        return str(resolved)

    return _PLACEHOLDER.sub(_sub, value)


def _render_list(node: list[Any], context: dict[str, Any], missing: list[str]) -> list[Any]:
    # A single-element list whose object carries __repeat__ is a row template.
    if len(node) == 1 and isinstance(node[0], dict) and REPEAT_KEY in node[0]:
        row = dict(node[0])
        source = row.pop(REPEAT_KEY)
        items = _lookup(str(source), context)
        if items is None:
            missing.append(str(source))
            return []
        if not isinstance(items, list):
            raise TemplateError(f"{source!r} is not a list, so it cannot be repeated")
        return [
            _render(row, {**context, ITEM_BINDING: item}, missing)
            for item in items
        ]

    return [_render(child, context, missing) for child in node]


def _render(node: Any, context: dict[str, Any], missing: list[str]) -> Any:
    if isinstance(node, str):
        return _render_string(node, context, missing)
    if isinstance(node, dict):
        return {k: _render(v, context, missing) for k, v in node.items()}
    if isinstance(node, list):
        return _render_list(node, context, missing)
    return node


def render(template: Any, context: dict[str, Any]) -> tuple[Any, list[str]]:
    """Fill `template` from `context`.

    Returns the rendered payload and the list of placeholders that resolved to
    nothing. Unresolved placeholders are reported rather than raised so the
    caller can decide: a missing optional field is fine, a missing PO number is
    not, and only the caller knows which is which.
    """
    missing: list[str] = []
    rendered = _render(template, context, missing)
    if missing:
        log.info("template rendered with gaps", missing=sorted(set(missing)))
    return rendered, missing


def placeholders(template: Any) -> set[str]:
    """Every placeholder a template references — used to validate a template
    against the fields the system can actually supply, before it is saved."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, str):
            found.update(_PLACEHOLDER.findall(node))
        elif isinstance(node, dict):
            for key, value in node.items():
                if key == REPEAT_KEY and isinstance(value, str):
                    found.add(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(template)
    return found
