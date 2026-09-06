from __future__ import annotations

import difflib
import re

_TOKEN = re.compile(r"\s+|[\wÀ-ÿ]+|[^\w\s]", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text)


def make_diff(original: str, proposed: str) -> list[dict]:
    """Return stable, user-reviewable token-level changes."""
    source = _tokens(original)
    target = _tokens(proposed)
    matcher = difflib.SequenceMatcher(a=source, b=target, autojunk=False)
    changes: list[dict] = []
    number = 0
    for tag, a1, a2, b1, b2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changes.append({
            "id": number,
            "kind": tag,
            "original": "".join(source[a1:a2]),
            "proposed": "".join(target[b1:b2]),
            "accepted": True,
        })
        number += 1
    return changes


def apply_diff(original: str, proposed: str, accepted_ids: set[int]) -> str:
    source = _tokens(original)
    target = _tokens(proposed)
    matcher = difflib.SequenceMatcher(a=source, b=target, autojunk=False)
    result: list[str] = []
    number = 0
    for tag, a1, a2, b1, b2 in matcher.get_opcodes():
        if tag == "equal":
            result.extend(source[a1:a2])
            continue
        if number in accepted_ids:
            result.extend(target[b1:b2])
        else:
            result.extend(source[a1:a2])
        number += 1
    return "".join(result)
