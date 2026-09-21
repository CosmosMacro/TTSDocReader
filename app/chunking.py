from __future__ import annotations

import regex as re
from typing import Iterable

# Split by paragraphs first, then by sentences if needed

PARA_SPLIT = re.compile(r"\n\n+")
# Split sentences on common end punctuation. Keep it ASCII and robust across encodings.
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _split_overlong(value: str, max_chars: int) -> list[str]:
    """Hard-wrap only when sentence boundaries cannot satisfy the limit."""
    result: list[str] = []
    remaining = value.strip()
    while len(remaining) > max_chars:
        boundary = remaining.rfind(" ", 0, max_chars + 1)
        if boundary <= 0:
            boundary = max_chars
        result.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].strip()
    if remaining:
        result.append(remaining)
    return result


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in PARA_SPLIT.split(text) if p.strip()]


def chunk_text(paragraphs: list[str], max_chars: int = 1500) -> list[str]:
    """Chunk into ~max_chars segments without cutting too aggressively.

    Around 1500–1800 characters generally works well (stay under context limits).
    """
    chunks: list[str] = []
    for para in paragraphs:
        if len(para) <= max_chars:
            chunks.append(para)
            continue

        # Split long paragraphs by sentences
        sentences = [s.strip() for s in SENT_SPLIT.split(para) if s.strip()]
        buf: list[str] = []
        cur = 0
        for sentence in sentences:
            for s in _split_overlong(sentence, max_chars):
                add_len = len(s) + (1 if buf else 0)
                if cur + add_len > max_chars and buf:
                    chunks.append(" ".join(buf).strip())
                    buf = [s]
                    cur = len(s)
                else:
                    buf.append(s)
                    cur += add_len
        if buf:
            chunks.append(" ".join(buf).strip())
    return chunks


def iter_chunks(text: str, max_chars: int = 1500) -> Iterable[str]:
    return chunk_text(split_paragraphs(text), max_chars=max_chars)

