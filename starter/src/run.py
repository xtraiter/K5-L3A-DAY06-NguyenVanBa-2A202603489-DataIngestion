"""Day 06 pipeline entry point.

Run from starter/ (venv active, Docker DB up):
    python -m src.run ingest      # PDF -> data/processed/pages.jsonl, data/manifest.json, page log
    python -m src.run index       # chunk A/B/C, embed, upsert into pgvector (+ re-ingest check)
    python -m src.run evaluate    # top-3 for every question x strategy, traces + metrics
    python -m src.run all
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from . import config
from .models import DocumentPage

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


# --------------------------------------------------------------------------- ingest
def ingest() -> list[DocumentPage]:
    from .ingestion import load_pdf

    if not config.RAW_PDF.exists():
        raise FileNotFoundError(f"{config.RAW_PDF} missing: run python scripts/download_corpus.py")
    digest = hashlib.sha256(config.RAW_PDF.read_bytes()).hexdigest()
    if digest != config.SOURCE["sha256"]:
        raise RuntimeError("PDF hash differs from the recorded snapshot; page IDs would not match.")

    start = time.perf_counter()
    pages, page_log = load_pdf(config.RAW_PDF, config.SOURCE["source_id"], config.SOURCE["local_path"])
    elapsed = time.perf_counter() - start

    _write_jsonl(config.PAGES_JSONL, [
        {"document_id": p.document_id, "source": p.source, "page": p.page, **p.metadata,
         "chars": len(p.text), "text": p.text} for p in pages])

    statuses = Counter(e["status"] for e in page_log)
    manifest = {
        "sources": [{
            **config.SOURCE,
            "physical_pages": len(page_log),
            "counted_content_pages": len(pages),
            "counted_page_ids": [p.page for p in pages],
            "chars_per_page": {str(p.page): len(p.text) for p in pages},
            "total_normalized_chars": sum(len(p.text) for p in pages),
            "page_status_counts": dict(statuses),
            "pages_by_ip_type": dict(Counter(p.metadata["ip_type"] for p in pages)),
        }],
        "page_counting_rule": (
            "Page IDs are 1-based physical PDF page numbers. Counted pages are the body of chapters 1-5: "
            "from each chapter's 'Introduction' bookmark page to its 'Assessment Questions' bookmark page, "
            "with text before 'Introduction' and from 'Assessment Questions' on removed. Excluded: cover, "
            "front matter/preface, chapter opener pages (figure + chapter outline only), assessment "
            "questions, glossary, answer key, index. A page counts only if it keeps >= "
            f"{300} normalized characters after removing running headers/footers and endnotes."),
        "normalization": (
            "Unicode NFKC; curly quotes -> ASCII quotes; bullets -> '-'; soft hyphen removed; "
            "whitespace collapsed; wrapped lines re-joined into paragraphs (blank line between); "
            "running headers/footers and page-bottom endnote blocks removed (counts in page log)."),
        "metadata_fields": {
            "document_id": "str, constant source id",
            "source": "str, repo-relative path of the PDF",
            "page": "int, physical PDF page (1-based)",
            "printed_page": "int|null, page number printed in the footer",
            "chapter": "int, from PDF bookmark 'Chapter N ...'",
            "chapter_title": "str, from PDF bookmark",
            "ip_type": "str in {patent, copyright, trademark, trade_secret}; mapped 1:1 from the chapter title",
            "section / section_title": "str, from PDF section bookmarks (e.g. '3.5' / 'Rights and Term')",
        },
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ingest_seconds": round(elapsed, 2),
    }
    _write_json(config.MANIFEST, manifest)
    _write_json(config.RESULTS / "ingest" / "page_log.json", page_log)
    print(f"ingest: {len(pages)} content pages / {len(page_log)} physical, "
          f"{manifest['sources'][0]['total_normalized_chars']} chars, {elapsed:.1f}s; status {dict(statuses)}")
    if len(pages) < 30:
        raise RuntimeError("Fewer than 30 content pages")
    return pages


def load_pages() -> list[DocumentPage]:
    rows = _read_jsonl(config.PAGES_JSONL)
    keys = ("document_id", "source", "page", "text", "chars")
    return [DocumentPage(r["document_id"], r["source"], r["page"], r["text"],
                         {k: v for k, v in r.items() if k not in keys}) for r in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["ingest", "index", "evaluate", "all"])
    args = parser.parse_args()
    if args.stage in ("ingest", "all"):
        ingest()
    if args.stage in ("index", "all"):
        index()
    if args.stage in ("evaluate", "all"):
        evaluate()


if __name__ == "__main__":
    main()
