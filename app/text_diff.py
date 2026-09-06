from __future__ import annotations

import difflib
import re

_TOKEN = re.compile(r"\s+|[\wÀ-ÿ]+|[^\w\s]", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text)


def make_diff_segments(original: str, proposed: str) -> list[dict]:
    """Return the complete text flow, including unchanged and changed segments."""
    source = _tokens(original)
    target = _tokens(proposed)
    matcher = difflib.SequenceMatcher(a=source, b=target, autojunk=False)
    segments: list[dict] = []
    number = 0
    for tag, a1, a2, b1, b2 in matcher.get_opcodes():
        segment = {
            "id": None if tag == "equal" else number,
            "kind": tag,
            "original": "".join(source[a1:a2]),
            "proposed": "".join(target[b1:b2]),
            "accepted": True,
        }
        segments.append(segment)
        if tag != "equal":
            number += 1
    return segments


def make_diff(original: str, proposed: str) -> list[dict]:
    """Return stable, user-reviewable token-level changes."""
    return [segment for segment in make_diff_segments(original, proposed) if segment["kind"] != "equal"]


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
