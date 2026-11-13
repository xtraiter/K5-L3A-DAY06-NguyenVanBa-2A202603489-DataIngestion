"""Fixed-size (strategy A) and structure-aware paragraph chunking (strategies B/C).

Chunks never cross a page boundary, so each chunk has exactly one source page.
Chunk text is always a slice page.text[start_char:end_char], so positions stay traceable.
"""
from __future__ import annotations

import hashlib
import re

from .ingestion import section_at
from .models import Chunk, DocumentPage

_SENTENCE_END = re.compile(r'(?<=[.!?])["\')\]]?\s+(?=[A-Z"(\[])')


def _make_chunk(page: DocumentPage, tag: str, index: int, start: int, end: int,
                chunking: str) -> Chunk:
    text = page.text[start:end]
    section, section_title = section_at(page, start)
    meta = {k: page.metadata.get(k) for k in ("chapter", "chapter_title", "ip_type", "printed_page")}
    meta.update(section=section, section_title=section_title, start_char=start, end_char=end,
                chunking=chunking, chars=len(text),
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16])
    return Chunk(chunk_id=f"{page.document_id}:p{page.page:03d}:{tag}:{index:03d}",
                 document_id=page.document_id, source=page.source, page=page.page,
                 text=text, metadata=meta)


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """Character windows of `size` with `overlap`, cut at exact offsets (no boundary logic)."""
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("require size > 0 and 0 <= overlap < size")
    chunks, step, start, i = [], size - overlap, 0, 0
    text = page.text
    while start < len(text):
        end = min(start + size, len(text))
        if text[start:end].strip():
            chunks.append(_make_chunk(page, f"fs{size}o{overlap}", i, start, end, "fixed_size"))
            i += 1
        if end == len(text):
            break
        start += step
    return chunks


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"\S(?:.|\n(?!\n))*", text)]


def _split_long(text: str, start: int, end: int, max_size: int) -> list[tuple[int, int]]:
    """Split an oversized paragraph at sentence ends; hard-cut a single huge sentence."""
    cuts = [start] + [start + m.end() for m in _SENTENCE_END.finditer(text[start:end])] + [end]
    sentences = [(a, b) for a, b in zip(cuts, cuts[1:]) if b > a]
    pieces, cur_s, cur_e = [], None, None
    for s, e in sentences:
        if cur_s is not None and e - cur_s > max_size:
            pieces.append((cur_s, cur_e))
            cur_s = None
        if cur_s is None:
            cur_s = s
        cur_e = e
        while cur_e - cur_s > max_size:  # single sentence longer than max_size
            pieces.append((cur_s, cur_s + max_size))
            cur_s += max_size
    if cur_s is not None:
        pieces.append((cur_s, cur_e))
    return [(a + len(text[a:b]) - len(text[a:b].lstrip()), b) for a, b in pieces if text[a:b].strip()]


def _is_heading(text: str) -> bool:
    t = text.strip()
    return len(t) < 80 and not re.search(r'[.!?:;,)"\']$', t)


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """Group whole paragraphs up to `max_size` chars.

    Structure rules: a section heading always starts a new chunk; a short heading
    is never left at the end of a chunk (it is carried to the next one); paragraphs
    longer than `max_size` are split at sentence boundaries.
    """
    text = page.text
    section_starts = {s["char"] for s in page.metadata.get("section_starts", [])}
    units: list[tuple[int, int]] = []
    for s, e in _paragraph_spans(text):
        units.extend(_split_long(text, s, e, max_size) if e - s > max_size else [(s, e)])

    groups: list[tuple[int, int]] = []
    cur: list[tuple[int, int]] = []
    for s, e in units:
        only_headings = all(_is_heading(text[a:b]) for a, b in cur)
        if cur and s in section_starts and not only_headings:
            groups.append((cur[0][0], cur[-1][1]))
            cur = []
        elif cur and e - cur[0][0] > max_size and not only_headings:
            # carry trailing headings into the next chunk
            tail = []
            while cur and _is_heading(text[cur[-1][0]:cur[-1][1]]):
                tail.insert(0, cur.pop())
            if cur:
                groups.append((cur[0][0], cur[-1][1]))
            cur = tail
        cur.append((s, e))
    if cur:
        groups.append((cur[0][0], cur[-1][1]))
    return [_make_chunk(page, f"para{max_size}", i, s, e, "by_paragraph")
            for i, (s, e) in enumerate(groups)]
