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


# --------------------------------------------------------------------------- index
HYPOTHESES = {
    "A": "Baseline: fixed 500-char windows cut sentences/quotes; expect lower evidence Hit@3 and coherence.",
    "B": "Paragraph/heading-aware chunks keep whole statements together; expect higher evidence Hit@3 "
         "and coherence than A at similar cost.",
    "C": "Same chunks as B plus ip_type filter (only when the question has one); expect gains on "
         "metadata-filter questions, identical results on the others.",
}


def build_chunks(pages: list[DocumentPage], cfg: dict[str, Any]) -> list:
    from .chunking import by_paragraph, fixed_size

    chunks = []
    for page in pages:
        if cfg["chunking"] == "fixed_size":
            chunks.extend(fixed_size(page, cfg["chunk_size"], cfg["overlap"]))
        elif cfg["chunking"] == "by_paragraph":
            chunks.extend(by_paragraph(page, cfg["chunk_size"]))
        else:
            raise ValueError(cfg["chunking"])
    return chunks


def _dist(values: list[int]) -> dict[str, float]:
    s = sorted(values)
    return {"min": s[0], "p10": s[int(0.1 * (len(s) - 1))], "median": statistics.median(s),
            "mean": round(statistics.fmean(s), 1), "p90": s[int(0.9 * (len(s) - 1))], "max": s[-1]}


def _store_and_embedder():
    from .embeddings import LocalEmbedder
    from .store import PgVectorStore

    embedder = LocalEmbedder()
    store = PgVectorStore(os.getenv("DATABASE_URL", ""), embedder.dimensions)
    store.create_schema()  # fails loudly if the DB is down; never falls back to mock vectors
    return embedder, store


def index() -> dict[str, Any]:
    pages = load_pages()
    t_load = time.perf_counter()
    embedder, store = _store_and_embedder()
    model_load_s = time.perf_counter() - t_load
    cache: dict[str, list[float]] = {}  # content_hash -> vector (B and C share identical chunk texts)
    stats: dict[str, Any] = {"embedder": embedder.info(), "model_load_seconds": round(model_load_s, 1),
                             "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             "machine": f"{platform.system()} {platform.release()}, {platform.processor()}",
                             "store": "PostgreSQL 16 + pgvector 0.8.7 (Docker), exact cosine search",
                             "strategies": {}}
    for name, cfg in config.STRATEGIES.items():
        t0 = time.perf_counter()
        chunks = build_chunks(pages, cfg)
        chunk_s = time.perf_counter() - t0
        existing = store.existing(name)
        need = [c for c in chunks
                if existing.get(c.chunk_id) != (c.metadata["content_hash"], embedder.model_name)]
        new_texts = {c.metadata["content_hash"]: c.text for c in need
                     if c.metadata["content_hash"] not in cache}
        t1 = time.perf_counter()
        if new_texts:
            for h, v in zip(new_texts, embedder.embed_documents(list(new_texts.values()))):
                cache[h] = v
        embed_s = time.perf_counter() - t1
        need_ids = {c.chunk_id for c in need}
        vectors = [cache[c.metadata["content_hash"]] if c.chunk_id in need_ids else None for c in chunks]
        t2 = time.perf_counter()
        counts = store.upsert(name, chunks, vectors, embedder.model_name)
        store_s = time.perf_counter() - t2
        tokens = embedder.token_lengths([c.text for c in chunks])
        stats["strategies"][name] = {
            **cfg,
            "chunk_count": len(chunks), "stored_rows": store.count(name),
            "chars": _dist([len(c.text) for c in chunks]),
            "total_chars": sum(len(c.text) for c in chunks),
            "tokens_with_prefix": _dist(tokens), "total_tokens": sum(tokens),
            "chunks_over_model_max_tokens": sum(t > embedder.max_seq_length for t in tokens),
            "texts_embedded_this_run": len(new_texts),
            "seconds": {"chunking": round(chunk_s, 2), "embedding": round(embed_s, 2),
                        "upsert": round(store_s, 2)},
            "upsert_counts": counts, "cost_usd": 0,
        }
        _write_jsonl(config.RESULTS / "chunks" / f"{name}.jsonl", [
            {"chunk_id": c.chunk_id, "document_id": c.document_id, "source": c.source, "page": c.page,
             **c.metadata, "text": c.text} for c in chunks])
        print(f"index {name}: {len(chunks)} chunks, embedded {len(new_texts)} in {embed_s:.1f}s, {counts}")

    stats["reingest_check"] = reingest_check(pages, embedder, store)
    _write_json(config.RESULTS / "index" / "index_stats.json", stats)
    return stats


def reingest_check(pages: list[DocumentPage], embedder, store) -> dict[str, Any]:
    """(1) Re-ingest the same version: nothing embedded/inserted, row counts unchanged.
    (2) Changed document: an edited page updates its chunks, a removed page's chunks are deleted."""
    result: dict[str, Any] = {"same_version": {}}
    for name, cfg in config.STRATEGIES.items():
        before = store.count(name)
        chunks = build_chunks(pages, cfg)
        existing = store.existing(name)
        need = [c for c in chunks
                if existing.get(c.chunk_id) != (c.metadata["content_hash"], embedder.model_name)]
        counts = store.upsert(name, chunks, [None] * len(chunks), embedder.model_name) if not need else None
        result["same_version"][name] = {"rows_before": before, "rows_after": store.count(name),
                                        "chunks_needing_embedding": len(need), "upsert_counts": counts,
                                        "no_duplicates": before == store.count(name) == len(chunks)}

    test_strategy = "_reingest_test"
    store.delete_strategy(test_strategy)
    v1 = [DocumentPage("reingest-test", p.source, p.page, p.text, dict(p.metadata)) for p in pages[:2]]
    c1 = build_chunks(v1, config.STRATEGIES["B"])
    counts1 = store.upsert(test_strategy, c1, embedder.embed_documents([c.text for c in c1]), embedder.model_name)
    edited = DocumentPage("reingest-test", v1[0].source, v1[0].page,
                          v1[0].text + "\n\nEdited paragraph added in version 2.", dict(v1[0].metadata))
    c2 = build_chunks([edited], config.STRATEGIES["B"])  # page 2 removed in version 2
    old = store.existing(test_strategy)
    vecs = [None if old.get(c.chunk_id, ("",))[0] == c.metadata["content_hash"] else v
            for c, v in zip(c2, embedder.embed_documents([c.text for c in c2]))]
    counts2 = store.upsert(test_strategy, c2, vecs, embedder.model_name)
    rows_after = store.count(test_strategy)
    store.delete_strategy(test_strategy)
    result["changed_document"] = {
        "v1_chunks": len(c1), "v1_upsert": counts1, "v2_chunks": len(c2), "v2_upsert": counts2,
        "rows_after_v2": rows_after, "ok": rows_after == len(c2) and counts2["deleted"] > 0,
        "note": "Synthetic document 'reingest-test' (copies of the first 2 pages) in a temporary "
                "strategy, removed afterwards: v2 edits page 1 and drops page 2.",
    }
    print(f"reingest check: {json.dumps(result)}")
    return result


# --------------------------------------------------------------------------- evaluate
def _fmt(n: int, d: int) -> str:
    return f"{n}/{d}"


def evaluate() -> dict[str, Any]:
    from .evaluation import evaluate_query, summarize

    questions = _read_jsonl(config.BENCHMARK)
    embedder, store = _store_and_embedder()
    t0 = time.perf_counter()
    qvecs = {q["id"]: embedder.embed_query(q["question"]) for q in questions}
    query_embed_s = time.perf_counter() - t0
    traces = []
    for name, cfg in config.STRATEGIES.items():
        if store.count(name) == 0:
            raise RuntimeError(f"strategy {name} has no stored chunks: run `python -m src.run index`")
        for q in questions:
            applied = q["filter"] if cfg["use_filter"] and q.get("filter") else None
            t = time.perf_counter()
            hits = store.search(name, qvecs[q["id"]], config.TOP_K, applied)
            latency = (time.perf_counter() - t) * 1000
            trace = evaluate_query(q, hits, applied)
            trace.update(strategy=name, search_ms=round(latency, 1))
            traces.append(trace)
    metrics = summarize(traces)

    # Pre-registered selection on dev: Hit@3, then Hit@1, then fewer chunks.
    index_stats = json.loads((config.RESULTS / "index" / "index_stats.json").read_text(encoding="utf-8"))
    chunk_counts = {k: v["chunk_count"] for k, v in index_stats["strategies"].items()}
    ranking = sorted(config.STRATEGIES, key=lambda s: (-metrics[s]["dev"]["evidence_hit_at_3"],
                                                       -metrics[s]["dev"]["hit_at_1"], chunk_counts[s]))
    run = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "embedder": embedder.info(), "top_k": config.TOP_K, "strategies": config.STRATEGIES,
        "query_embedding_seconds": round(query_embed_s, 2),
        "metrics": metrics,
        "selection": {"criterion": "dev evidence Hit@3 > dev Hit@1 > fewer chunks (pre-registered)",
                      "dev_ranking": ranking, "selected": ranking[0]},
    }
    out = config.RESULTS / "runs"
    _write_jsonl(out / "traces.jsonl", traces)
    _write_json(out / "metrics.json", run)

    lines = ["| Strategy | Split | Hit@1 | Evidence Hit@3 | Page Hit@3 | Split-evidence suspects | "
             "Filter compliant top-3 | Chunks |", "|---|---|---|---|---|---|---|---|"]
    for s in config.STRATEGIES:
        for split in ("dev", "test", "all"):
            m = metrics[s][split]
            fc = _fmt(m["filter_compliant_top3"], m["filter_questions"]) if m["filter_questions"] else "N/A"
            lines.append(f"| {s} | {split} | {_fmt(m['hit_at_1'], m['N'])} | "
                         f"{_fmt(m['evidence_hit_at_3'], m['N'])} | {_fmt(m['page_hit_at_3'], m['N'])} | "
                         f"{m['split_evidence_suspect']} | {fc} | {chunk_counts[s]} |")
    lines += ["", f"Selected on dev (pre-registered criterion): **{ranking[0]}** (ranking {ranking})"]
    (out / "metrics.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    rows = ["strategy,chunking,chunk_size,overlap,metadata,filter,vectorizer,hypothesis,"
            "dev_hit1,dev_hit3,test_hit1,test_hit3,notes"]
    for s, cfg in config.STRATEGIES.items():
        d, t = metrics[s]["dev"], metrics[s]["test"]
        notes = (f"{chunk_counts[s]} chunks; selected={s == ranking[0]}; "
                 f"filter compliance dev {d['filter_compliant_top3']}/{d['filter_questions']} "
                 f"test {t['filter_compliant_top3']}/{t['filter_questions']}")
        rows.append(",".join([
            s, cfg["chunking"], str(cfg["chunk_size"]), str(cfg["overlap"]),
            "document_id+source+page+printed_page+chapter+ip_type+section",
            "ip_type when question has filter" if cfg["use_filter"] else "none",
            f"{embedder.model_name} (local; {embedder.dimensions}d; cosine; pgvector exact)",
            '"' + HYPOTHESES[s].replace('"', "'") + '"',
            _fmt(d["hit_at_1"], d["N"]), _fmt(d["evidence_hit_at_3"], d["N"]),
            _fmt(t["hit_at_1"], t["N"]), _fmt(t["evidence_hit_at_3"], t["N"]), '"' + notes + '"']))
    (config.ARTIFACTS / "experiment_log.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print((out / "metrics.md").read_text(encoding="utf-8"))
    return run


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
