from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
import posixpath
import re
from typing import Iterable
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from .text_extract import extract_text, normalize_text


@dataclass
class Chapter:
    title: str
    text: str
    index: int = 0


@dataclass
class Book:
    title: str
    author: str | None
    source: Path
    chapters: list[Chapter] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(c.text for c in self.chapters if c.text)


class _NavigationParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href:
            label = normalize_text(" ".join("".join(self._text).split()))
            if label:
                self.links.append((self._href, label))
            self._href = None
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)


class _XhtmlText(HTMLParser):
    """Extract readable XHTML text while retaining heading boundaries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.headings: list[str] = []
        self._skip = 0
        self._heading_depth = 0
        self._heading_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "svg", "nav"}:
            self._skip += 1
        if self._skip:
            return
        if tag in {"h1", "h2", "h3"}:
            self._heading_depth += 1
            self._heading_parts = []
        elif tag in {"p", "div", "section", "br", "li", "blockquote"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._skip:
            if tag in {"script", "style", "svg", "nav"}:
                self._skip -= 1
            return
        if tag in {"h1", "h2", "h3"} and self._heading_depth:
            heading = normalize_text("".join(self._heading_parts))
            if heading:
                self.headings.append(heading)
            self._heading_depth -= 1
        elif tag in {"p", "div", "section", "li", "blockquote"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._heading_depth:
            self._heading_parts.append(data)
        else:
            self.parts.append(data)

    @property
    def text(self) -> str:
        return normalize_text("".join(self.parts))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _metadata(root: ET.Element, name: str) -> str | None:
    for element in root.iter():
        if _local(element.tag) == name and element.text:
            value = normalize_text(element.text)
            if value:
                return value
    return None


def _resolve_zip_path(base: str, href: str) -> str:
    href = href.split("#", 1)[0]
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), href))


def _navigation_entries(archive: ZipFile, opf_path: str, items: dict[str, tuple[str, str]]) -> tuple[dict[str, list[tuple[str | None, str]]], set[str]]:
    """Return content-path -> ordered (fragment, title) entries from EPUB navigation."""
    from urllib.parse import unquote

    entries: dict[str, list[tuple[str | None, str]]] = {}
    nav_paths: set[str] = set()

    def add_entry(base: str, target: str, label: str) -> None:
        target_path, _, fragment = target.partition("#")
        path = _resolve_zip_path(base, target_path)
        entries.setdefault(path, []).append((unquote(fragment) or None, label))

    for item_id, (href, properties) in items.items():
        if "nav" in properties.split():
            nav_paths.add(href)
            try:
                parser = _NavigationParser()
                parser.feed(archive.read(href).decode("utf-8", errors="replace"))
                for target, label in parser.links:
                    add_entry(href, target, label)
            except (KeyError, ValueError):
                pass
    for item_id, (href, media_type) in items.items():
        if media_type != "application/x-dtbncx+xml" or href not in archive.namelist():
            continue
        try:
            root = ET.fromstring(archive.read(href))
            for point in root.iter():
                if _local(point.tag) != "navPoint":
                    continue
                label = next((normalize_text(x.text or "") for x in point.iter() if _local(x.tag) == "text" and x.text), "")
                content = next((x.attrib.get("src") for x in point.iter() if _local(x.tag) == "content" and x.attrib.get("src")), None)
                if label and content:
                    add_entry(href, content, label)
        except (ET.ParseError, KeyError):
            pass
    return entries, nav_paths


def _best_navigation_title(entries: list[tuple[str | None, str]]) -> str | None:
    """Choose a meaningful file-level title, ignoring page-number anchors."""
    for _fragment, title in entries:
        clean = normalize_text(title)
        if not clean or re.fullmatch(r"\d+", clean):
            continue
        if clean.casefold() in {"références", "references"}:
            continue
        return clean
    return None


def _parse_epub(path: Path) -> Book:
    with ZipFile(path) as archive:
        container = ET.fromstring(archive.read("META-INF/container.xml"))
        rootfile = next((x for x in container.iter() if _local(x.tag) == "rootfile"), None)
        if rootfile is None or not rootfile.attrib.get("full-path"):
            raise ValueError("EPUB container has no rootfile")
        opf_path = rootfile.attrib["full-path"]
        opf = ET.fromstring(archive.read(opf_path))

        manifest: dict[str, str] = {}
        item_meta: dict[str, tuple[str, str]] = {}
        for item in opf.iter():
            if _local(item.tag) == "item" and item.attrib.get("id") and item.attrib.get("href"):
                item_id = item.attrib["id"]
                href = _resolve_zip_path(opf_path, item.attrib["href"])
                manifest[item_id] = href
                item_meta[item_id] = (href, item.attrib.get("properties", "") or item.attrib.get("media-type", ""))

        spine_ids = [item.attrib.get("idref") for item in opf.iter() if _local(item.tag) == "itemref"]
        navigation_entries, navigation_paths = _navigation_entries(archive, opf_path, item_meta)
        chapters: list[Chapter] = []
        for source_index, item_id in enumerate(spine_ids):
            href = manifest.get(item_id or "")
            if not href or href in navigation_paths or href not in archive.namelist():
                continue
            raw = archive.read(href).decode("utf-8", errors="replace")
            parser = _XhtmlText()
            parser.feed(raw)
            text = parser.text
            if not text:
                continue
            entries = navigation_entries.get(href, [])
            title = _best_navigation_title(entries) or (parser.headings[0] if parser.headings else f"Chapitre {len(chapters) + 1}")
            chapters.append(Chapter(title=title, text=text, index=len(chapters) + 1))

        if not chapters:
            raise ValueError("EPUB contains no readable chapters")
        return Book(
            title=_metadata(opf, "title") or path.stem,
            author=_metadata(opf, "creator"),
            source=path,
            chapters=chapters,
        )


def split_text_into_chapters(text: str) -> list[Chapter]:
    """Split plain text on common French/English chapter headings."""
    clean = normalize_text(text)
    if not clean:
        return []
    pattern = re.compile(
        r"(?im)^(?P<title>(?:chapitre|chapter|partie|part|section)\s+[^\n]{1,160})\s*$"
    )
    matches = list(pattern.finditer(clean))
    if not matches:
        return [Chapter(title="Document", text=clean, index=1)]

    chapters: list[Chapter] = []
    if matches[0].start() > 0:
        preface = clean[: matches[0].start()].strip()
        if preface:
            chapters.append(Chapter(title="Avant-propos", text=preface, index=1))
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(clean)
        body = clean[start:end].strip()
        chapters.append(Chapter(title=match.group("title").strip(), text=body, index=len(chapters) + 1))
    return chapters


def apply_chapter_titles(book: Book, titles: Iterable[str]) -> Book:
    """Return a copy with user-corrected titles while preserving chapter text."""
    corrected = list(titles)
    if len(corrected) != len(book.chapters):
        raise ValueError(f"Expected {len(book.chapters)} chapter titles, got {len(corrected)}")
    chapters = [
        Chapter(title=(title.strip() or chapter.title), text=chapter.text, index=chapter.index)
        for chapter, title in zip(book.chapters, corrected)
    ]
    return Book(title=book.title, author=book.author, source=book.source, chapters=chapters)


def load_book(path: str | Path) -> Book:
    source = Path(path)
    if source.suffix.lower() == ".epub":
        return _parse_epub(source)
    if source.suffix.lower() == ".pdf":
        text = extract_text(source)
        return Book(source.stem, None, source, split_text_into_chapters(text))
    if source.suffix.lower() in {".txt", ".md"}:
        text = extract_text(source)
        return Book(source.stem, None, source, split_text_into_chapters(text))
    raise ValueError(f"Unsupported book extension: {source.suffix}")
