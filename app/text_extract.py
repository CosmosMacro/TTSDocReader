from __future__ import annotations

import re
from pathlib import Path

# Optional PDF support (PyMuPDF)
try:
    import fitz  # type: ignore
except Exception:  # pragma: no cover
    fitz = None  # type: ignore

# Optional DOCX support
try:
    import docx  # type: ignore
except Exception:  # pragma: no cover
    docx = None  # type: ignore


SUPPORTED_EXTS = {".pdf", ".docx", ".txt", ".md"}
HARD_BREAK = "\n\n"


def normalize_text(text: str) -> str:
    """Light cleanup: fix hyphenated line-breaks, collapse lines into paragraphs.

    - Removes CR (\r)
    - Joins word-hyphen-newline patterns (e.g., "com-\nplex" -> "complex")
    - Collapses single newlines within paragraphs; preserves blank lines as paragraph breaks
    """
    text = text.replace("\r", "")
    # join hyphenated line breaks between alphanumerics
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    lines = [ln.strip() for ln in text.splitlines()]
    paragraphs: list[str] = []
    buf: list[str] = []
    for ln in lines:
        if not ln:
            if buf:
                paragraphs.append(" ".join(buf))
                buf = []
        else:
            buf.append(ln)
    if buf:
        paragraphs.append(" ".join(buf))

    clean = HARD_BREAK.join(p.strip() for p in paragraphs if p.strip())
    # normalize multiple spaces
    clean = re.sub(r"[ \t\f\v]+", " ", clean)
    return clean.strip()


def extract_text(path: str | Path) -> str:
    """Extract text from PDF/DOCX/TXT/MD and normalize it.

    Raises:
        ValueError: unsupported extension
        RuntimeError: required optional dependency missing
    """
    p = Path(path)
    ext = p.suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise ValueError(f"Unsupported extension: {ext}")

    if ext == ".pdf":
        if fitz is None:
            raise RuntimeError("PyMuPDF is not installed. Install with: pip install pymupdf")
        doc = fitz.open(p.as_posix())
        pages: list[str] = []
        for pg in doc:
            pages.append(pg.get_text("text"))
        raw = "\n".join(pages)
        return normalize_text(raw)

    if ext == ".docx":
        if docx is None:
            raise RuntimeError("python-docx is not installed. Install with: pip install python-docx")
        d = docx.Document(p)
        raw = "\n".join(par.text for par in d.paragraphs)
        return normalize_text(raw)

    if ext in {".txt", ".md"}:
        # Use utf-8-sig to gracefully strip an optional BOM (\ufeff)
        raw = p.read_text(encoding="utf-8-sig", errors="ignore")
        return normalize_text(raw)

    raise AssertionError("Unreachable: extension guard should return earlier")
