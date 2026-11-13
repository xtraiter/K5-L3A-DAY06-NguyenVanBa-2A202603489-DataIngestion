"""Build the samples for manual audit (labels are written by a person, not by this script).

Run from starter/ after `python -m src.run index` and `evaluate`:
    python scripts/make_audit_samples.py

Outputs in results/audit/:
- coherence_positions.json : 10 fixed source positions (chosen by rule, independent of scores)
- coherence_sample.jsonl   : the chunk covering each position, per strategy
- metadata_sample.jsonl    : test questions x top-3 x strategy, with a script cross-check of
                             source/page/printed page against a fresh PDF extraction
- grounding_sample.jsonl   : test questions x strategy with the top-3 texts to label 0/1/2
"""
import json
import re
import sys
from pathlib import Path

import pypdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config  # noqa: E402
from src.ingestion import normalize_text  # noqa: E402

OUT = config.RESULTS / "audit"
OUT.mkdir(parents=True, exist_ok=True)


def read_jsonl(path):
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def squash(text: str) -> str:
    """Whitespace-free comparison form (robust to line re-joining)."""
    return re.sub(r"\s+", "", normalize_text(text)).lower()


pages = read_jsonl(config.PAGES_JSONL)

# 1) Coherence positions: 10 evenly spaced content pages, middle character of each page.
n = len(pages)
positions = []
for i in range(10):
    p = pages[round(i * (n - 1) / 9)]
    positions.append({"position_id": f"pos{i + 1:02d}", "page": p["page"], "char": len(p["text"]) // 2,
                      "rule": "pages[round(i*(N-1)/9)], i=0..9, char = len(page_text)//2"})
(OUT / "coherence_positions.json").write_text(json.dumps(positions, indent=2) + "\n", encoding="utf-8")

coherence = []
for strategy in config.STRATEGIES:
    chunks = read_jsonl(config.RESULTS / "chunks" / f"{strategy}.jsonl")
    for pos in positions:
        covering = [c for c in chunks if c["page"] == pos["page"]
                    and c["start_char"] <= pos["char"] < c["end_char"]]
        c = min(covering, key=lambda c: c["start_char"])  # earliest window if overlapping
        coherence.append({**pos, "strategy": strategy, "chunk_id": c["chunk_id"],
                          "covering_chunks": len(covering), "section": c["section"],
                          "chars": c["chars"], "text": c["text"]})
with (OUT / "coherence_sample.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
    for row in coherence:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

# 2) Metadata + 3) grounding samples from the test traces.
reader = pypdf.PdfReader(str(config.RAW_PDF))
raw_pages = {i + 1: squash(pg.extract_text() or "") for i, pg in enumerate(reader.pages)}
traces = [t for t in read_jsonl(config.RESULTS / "runs" / "traces.jsonl") if t["split"] == "test"]
metadata, grounding = [], []
for t in traces:
    for h in t["hits"]:
        text_on_page = squash(h["text"]) in raw_pages[h["page"]]
        metadata.append({
            "strategy": t["strategy"], "id": t["id"], "rank": h["rank"], "chunk_id": h["chunk_id"],
            "document_id": h["document_id"], "source": h["source"], "page": h["page"],
            "printed_page": h["printed_page"], "chapter": h["chapter"], "section": h["section"],
            "section_title": h["section_title"], "ip_type": h["ip_type"],
            "question_filter": t["question_filter"],
            "check_source": h["source"] == config.SOURCE["local_path"]
                            and h["document_id"] == config.SOURCE["source_id"],
            "check_text_found_on_pdf_page": text_on_page,
            "check_printed_page_offset_8": h["printed_page"] == h["page"] - 8
                                           if h["printed_page"] is not None else None,
            "text": h["text"],
        })
    grounding.append({"strategy": t["strategy"], "id": t["id"], "question": t["question"],
                      "expected_answer": t["expected_answer"], "gold_pages": t["gold_pages"],
                      "auto_evidence_hit_at_3": t["hit_at_3"],
                      "top3": [{"rank": h["rank"], "page": h["page"], "section": h["section"],
                                "text": h["text"]} for h in t["hits"]]})
for name, rows in (("metadata_sample.jsonl", metadata), ("grounding_sample.jsonl", grounding)):
    with (OUT / name).open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
print(f"coherence {len(coherence)} rows, metadata {len(metadata)} rows, grounding {len(grounding)} rows")
