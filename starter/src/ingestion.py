"""Read and normalize the OpenStax PDF into page records with traceable metadata.

Metadata (chapter, section, ip_type) comes from the PDF's own bookmarks, never
from guessing. Page numbers are 1-based physical PDF page numbers; the printed
book page number is kept separately as `printed_page`.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pypdf

from .models import DocumentPage

# Chapter number -> filter value. Values come from the chapter titles in the
# PDF outline ("Patent Basics", "Patent Enforcement", "Copyright Basics", ...).
IP_TYPE_BY_CHAPTER_TITLE = {
    "Patent Basics": "patent",
    "Patent Enforcement": "patent",
    "Copyright Basics": "copyright",
    "Trademark Basics": "trademark",
    "Trade Secret Basics": "trade_secret",
}

MIN_CONTENT_CHARS = 300  # pages below this after cleaning are logged, not counted

_QUOTES = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "′": "'", "″": '"', "­": None,  # soft hyphen removed
    "•": "-", "●": "-",                  # bullets -> "-"
})

# Running headers/footers of OpenStax PDFs, matched after normalize_text
# (bullets already mapped to "-", runs of spaces collapsed).
_FOOTER_PATTERNS = [
    re.compile(r"^Access for free at openstax\.org$"),
    re.compile(r"^\d+ \d+ - [A-Z][^.]*$"),                 # "12 1 - Patent Basics"
    re.compile(r"^\d+\.\d+ - [A-Z].* \d+$"),               # "1.1 - The Foundations ... 11"
]
_SECTION_HEADING = re.compile(r"^(\d+\.\d+)\s+(.+)$")
# Endnote lines at the page bottom start with a lower-case roman numeral: "xiv Derived from 17 U.S.C."
_FOOTNOTE_START = re.compile(r"^[ivxl]{1,7} {1,2}\S")


def _split_footnotes(lines: list[str]) -> tuple[list[str], list[str]]:
    """Cut the endnote block: from the first roman-numeral line in the bottom
    half of the page to the end. Returns (body_lines, footnote_lines)."""
    for i in range(len(lines) // 2, len(lines)):
        if _FOOTNOTE_START.match(lines[i]):
            return lines[:i], lines[i:]
    return lines, []


def normalize_text(text: str) -> str:
    """NFKC + ASCII quotes/bullets, collapse spaces inside lines, keep line breaks."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES)
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.splitlines()]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def normalize_for_match(text: str) -> str:
    """Comparison form for evidence matching: normalized, lower-case, single spaces."""
    return re.sub(r"\s+", " ", normalize_text(text)).strip().lower()


@dataclass
class OutlineEntry:
    title: str
    page: int  # 1-based PDF page
    depth: int


def read_outline(reader: pypdf.PdfReader) -> list[OutlineEntry]:
    entries: list[OutlineEntry] = []

    def walk(items: list[Any], depth: int) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item, depth + 1)
            else:
                entries.append(OutlineEntry(normalize_text(item.title),
                                            reader.get_destination_page_number(item) + 1, depth))

    walk(reader.outline, 0)
    return entries


def _chapters(outline: list[OutlineEntry]) -> list[dict[str, Any]]:
    """Group the outline into chapters with section start pages and content range."""
    chapters: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for entry in outline:
        match = re.match(r"^Chapter (\d+) (.+)$", entry.title) if entry.depth == 0 else None
        if match:
            current = {"chapter": int(match.group(1)), "chapter_title": match.group(2),
                       "start_page": entry.page, "sections": [], "intro_page": None,
                       "assessment_page": None}
            chapters.append(current)
            continue
        if entry.depth == 0:
            current = None
            continue
        if current is None:
            continue
        sec = _SECTION_HEADING.match(entry.title)
        if sec:
            current["sections"].append({"section": sec.group(1), "section_title": sec.group(2),
                                        "page": entry.page, "heading": entry.title})
        elif entry.title == "Introduction":
            current["intro_page"] = entry.page
        elif entry.title == "Assessment Questions":
            current["assessment_page"] = entry.page
    for ch in chapters:
        if ch["chapter_title"] not in IP_TYPE_BY_CHAPTER_TITLE:
            raise ValueError(f"No ip_type mapping for chapter title {ch['chapter_title']!r}")
        ch["ip_type"] = IP_TYPE_BY_CHAPTER_TITLE[ch["chapter_title"]]
    return chapters


def _strip_running_lines(lines: list[str]) -> tuple[list[str], int | None, int]:
    """Remove headers/footers; return kept lines, printed page number, removed count."""
    kept, printed, removed = [], None, 0
    for line in lines:
        raw = line.strip()
        if any(p.match(raw) for p in _FOOTER_PATTERNS):
            removed += 1
            nums = re.findall(r"\d+", raw)
            if raw[:1].isdigit() and "." not in raw.split()[0]:
                printed = int(nums[0])       # even page: number first
            elif nums:
                printed = int(nums[-1])      # odd page: number last
            continue
        kept.append(line)
    return kept, printed, removed


def _to_paragraphs(lines: list[str]) -> str:
    """Re-join wrapped PDF lines into paragraphs separated by blank lines.

    Heuristic: a line much shorter than the page's typical full line, a heading,
    a list item or a figure caption ends the current paragraph.
    """
    lines = [l for l in lines if l.strip()]
    if not lines:
        return ""
    widths = sorted(len(l) for l in lines)
    full = widths[int(len(widths) * 0.8)] if len(widths) > 4 else max(widths)
    paragraphs: list[str] = []
    buf = ""

    def starts_block(line: str) -> bool:
        return bool(re.match(r"^(- |\d+\. |\d+\.\d+ [A-Z]|Figure \d|Table \d|Learning Objectives)", line))

    for line in lines:
        if buf and starts_block(line):
            paragraphs.append(buf)
            buf = ""
        if buf.endswith("-") and line[:1].islower():
            buf = buf + line
        else:
            buf = f"{buf} {line}".strip()
        if len(line) < 0.7 * full:
            paragraphs.append(buf)
            buf = ""
    if buf:
        paragraphs.append(buf)
    return "\n\n".join(p.strip() for p in paragraphs if p.strip())


def load_pdf(path: Path, document_id: str, source: str) -> tuple[list[DocumentPage], list[dict[str, Any]]]:
    """Extract chapter body pages with metadata; return (pages, page_log).

    page_log records every physical page with its status so excluded, empty or
    low-text pages are visible to the grader.
    """
    reader = pypdf.PdfReader(str(path))
    chapters = _chapters(read_outline(reader))
    page_log: list[dict[str, Any]] = []
    pages: list[DocumentPage] = []

    in_scope: dict[int, dict[str, Any]] = {}
    for ch in chapters:
        if ch["intro_page"] is None or ch["assessment_page"] is None:
            raise ValueError(f"Chapter {ch['chapter']} outline lacks Introduction/Assessment")
        for p in range(ch["intro_page"], ch["assessment_page"] + 1):
            in_scope[p] = ch

    for number in range(1, len(reader.pages) + 1):
        entry: dict[str, Any] = {"page": number}
        if number not in in_scope:
            entry["status"] = "excluded_out_of_scope"
            page_log.append(entry)
            continue
        ch = in_scope[number]
        try:
            raw = reader.pages[number - 1].extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - logged, page skipped
            entry.update(status="error", error=repr(exc))
            page_log.append(entry)
            continue
        lines, printed, removed = _strip_running_lines(normalize_text(raw).splitlines())

        # Trim chapter-opener material before "Introduction" and assessment material after it.
        if number == ch["intro_page"] and "Introduction" in lines:
            lines = lines[len(lines) - 1 - lines[::-1].index("Introduction") + 1:]
        if number == ch["assessment_page"] and "Assessment Questions" in lines:
            lines = lines[:lines.index("Assessment Questions")]
        lines, footnotes = _split_footnotes(lines)

        text = _to_paragraphs(lines)
        entry.update(chapter=ch["chapter"], printed_page=printed, removed_running_lines=removed,
                     removed_footnote_lines=len(footnotes), chars=len(text))
        if not text:
            entry["status"] = ("empty_after_trim_assessment" if number == ch["assessment_page"]
                               else "empty")
            page_log.append(entry)
            continue

        # Section active at page start = last section starting on an earlier page;
        # headings of sections starting on this page are located in the text.
        earlier = [s for s in ch["sections"] if s["page"] < number]
        starts = []
        for s in (s for s in ch["sections"] if s["page"] == number):
            pos = text.rfind(s["heading"])  # rfind skips the chapter outline list
            if pos >= 0:
                starts.append({"section": s["section"], "section_title": s["section_title"],
                               "char": pos})
        start_section = earlier[-1] if earlier else None

        status = "content" if len(text) >= MIN_CONTENT_CHARS else "low_text"
        entry["status"] = status
        page_log.append(entry)
        if status != "content":
            continue
        pages.append(DocumentPage(
            document_id=document_id, source=source, page=number, text=text,
            metadata={
                "chapter": ch["chapter"], "chapter_title": ch["chapter_title"],
                "ip_type": ch["ip_type"], "printed_page": printed,
                "section": start_section["section"] if start_section else None,
                "section_title": start_section["section_title"] if start_section else None,
                "section_starts": starts,
            },
        ))
    return pages, page_log


def section_at(page: DocumentPage, char: int) -> tuple[str | None, str | None]:
    """Section (number, title) covering character offset `char` of a page."""
    section, title = page.metadata.get("section"), page.metadata.get("section_title")
    for start in page.metadata.get("section_starts", []):
        if start["char"] <= char:
            section, title = start["section"], start["section_title"]
    return section, title
