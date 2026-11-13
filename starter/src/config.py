"""Paths, corpus source and the three strategy configurations (single source of truth)."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"
RAW_PDF = DATA / "raw" / "introduction-intellectual-property.pdf"
PAGES_JSONL = DATA / "processed" / "pages.jsonl"
MANIFEST = DATA / "manifest.json"
BENCHMARK = REPO / "benchmark" / "questions.jsonl"
RESULTS = REPO / "results"
ARTIFACTS = REPO / "artifacts"

SOURCE = {
    "source_id": "openstax-intro-ip",
    "title": "Introduction to Intellectual Property (OpenStax)",
    "source_path_or_url": "https://assets.openstax.org/oscms-prodcms/media/documents/"
                          "introduction-intellectual-property_-_WEB.pdf",
    "book_page": "https://openstax.org/details/books/introduction-intellectual-property",
    "local_path": "data/raw/introduction-intellectual-property.pdf",
    "sha256": "1498509864d37cb63a6ccc11bab7c783f3d30b2ed37d808ef80c56fdb676378a",
    "license_or_permission": "CC BY 4.0 (Creative Commons Attribution 4.0 International), "
                             "as listed by the OpenStax catalog API; redistribution allowed with attribution. "
                             "Attribution: Introduction to Intellectual Property, OpenStax, "
                             "https://openstax.org/details/books/introduction-intellectual-property",
    "accessed_at": "2026-11-13",
    "version_snapshot": "PDF /ModDate 2026-04-20 (Prince 16.2); HTTP Last-Modified 2026-04-22",
    "language": "en",
}

# A vs B: only the chunking method changes. B vs C: only the metadata filter changes.
STRATEGIES = {
    "A": {"chunking": "fixed_size", "chunk_size": 500, "overlap": 50, "use_filter": False},
    "B": {"chunking": "by_paragraph", "chunk_size": 1200, "overlap": 0, "use_filter": False},
    "C": {"chunking": "by_paragraph", "chunk_size": 1200, "overlap": 0, "use_filter": True},
}
FILTER_FIELDS = ("ip_type",)  # metadata keys a question may filter on
TOP_K = 3
