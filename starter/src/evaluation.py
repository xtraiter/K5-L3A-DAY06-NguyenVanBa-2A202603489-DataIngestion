"""Automatic retrieval metrics and per-query traces.

Evidence hit (rank r): the chunk is from the gold source, on a gold/alternative page,
and contains the FULL evidence quote of that page (after normalization).
Human labels (coherence, metadata correctness, grounding) are NOT inferred here;
they live in results/audit/*.csv.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .ingestion import normalize_for_match


def _golds(question: dict[str, Any]) -> list[tuple[int, str]]:
    golds = [(question["gold_page"], question["evidence_quote"])]
    golds += [(a["gold_page"], a["evidence_quote"]) for a in question.get("alternatives", [])]
    return golds


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]],
                   applied_filter: dict[str, Any] | None = None) -> dict[str, Any]:
    golds = _golds(question)
    gold_pages = {p for p, _ in golds}
    scored = []
    for hit in hits:
        same_source = hit["document_id"] == question["gold_source_id"]
        page_match = same_source and hit["page"] in gold_pages
        chunk_norm = normalize_for_match(hit["text"])
        evidence_hit = page_match and any(
            p == hit["page"] and normalize_for_match(q) in chunk_norm for p, q in golds)
        satisfies = None
        if question.get("filter"):
            satisfies = all(hit.get(k) == v for k, v in question["filter"].items())
        scored.append({
            "rank": hit["rank"], "chunk_id": hit["chunk_id"], "score": round(float(hit["score"]), 6),
            "document_id": hit["document_id"], "source": hit["source"], "page": hit["page"],
            "printed_page": hit.get("printed_page"), "chapter": hit.get("chapter"),
            "ip_type": hit.get("ip_type"), "section": hit.get("section"),
            "section_title": hit.get("section_title"),
            "page_match": page_match, "evidence_hit": evidence_hit,
            "satisfies_question_filter": satisfies, "text": hit["text"],
        })
    return {
        "id": question["id"], "split": question["split"], "type": question.get("type"),
        "question": question["question"], "expected_answer": question["expected_answer"],
        "gold_source_id": question["gold_source_id"], "gold_pages": sorted(gold_pages),
        "evidence_quote": question["evidence_quote"],
        "question_filter": question.get("filter"), "applied_filter": applied_filter,
        "hit_at_1": bool(scored) and scored[0]["evidence_hit"],
        "hit_at_3": any(h["evidence_hit"] for h in scored[:3]),
        "page_hit_at_3": any(h["page_match"] for h in scored[:3]),
        # page right but quote not fully inside one chunk: evidence split / truncated
        "split_evidence_suspect": any(h["page_match"] for h in scored[:3])
                                  and not any(h["evidence_hit"] for h in scored[:3]),
        "filter_compliant_top3": (all(h["satisfies_question_filter"] for h in scored[:3])
                                  if question.get("filter") else None),
        "hits": scored,
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts n/N of Hit@1, Evidence Hit@3, page Hit@3 and filter compliance per strategy x split."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for t in traces:
        groups[(t["strategy"], t["split"])].append(t)
        groups[(t["strategy"], "all")].append(t)
    out: dict[str, Any] = {}
    for (strategy, split), items in sorted(groups.items()):
        n = len(items)
        filt = [t for t in items if t["question_filter"]]
        out.setdefault(strategy, {})[split] = {
            "N": n,
            "hit_at_1": sum(t["hit_at_1"] for t in items),
            "evidence_hit_at_3": sum(t["hit_at_3"] for t in items),
            "page_hit_at_3": sum(t["page_hit_at_3"] for t in items),
            "split_evidence_suspect": sum(t["split_evidence_suspect"] for t in items),
            "filter_questions": len(filt),
            "filter_compliant_top3": sum(bool(t["filter_compliant_top3"]) for t in filt),
            "filter_questions_hit_at_3": sum(t["hit_at_3"] for t in filt),
        }
    return out
