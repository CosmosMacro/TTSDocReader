from __future__ import annotations

import re

from .text_extract import normalize_text


_PAGE_NUMBER = re.compile(r"^\s*(?:page\s+)?\d+\s*$", re.IGNORECASE)


def normalize_newlines(text: str) -> str:
    """Use LF as the canonical in-memory newline representation."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def clean_for_speech(text: str) -> str:
    """Apply conservative, deterministic layout cleanup for narration."""
    text = normalize_newlines(text)
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    lines = [line.rstrip() for line in text.split("\n")]
    lines = [line for line in lines if not _PAGE_NUMBER.match(line)]
    text = "\n".join(lines)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return normalize_text(text)
