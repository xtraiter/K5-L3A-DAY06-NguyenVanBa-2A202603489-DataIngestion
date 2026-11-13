"""Pre-run benchmark check: schema, dev/test split, filters and that every evidence
quote really occurs on its gold page after normalization.

Run from starter/ after `python -m src.run ingest`:  python scripts/verify_benchmark.py
Writes benchmark/verification.json. Exit code 1 on any failure.
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config  # noqa: E402
from src.ingestion import normalize_for_match  # noqa: E402

REQUIRED = ["id", "split", "question", "expected_answer", "gold_source_id", "gold_page", "evidence_quote"]

pages = {}
for line in config.PAGES_JSONL.read_text(encoding="utf-8").splitlines():
    row = json.loads(line)
    pages[(row["document_id"], row["page"])] = row
questions = [json.loads(l) for l in config.BENCHMARK.read_text(encoding="utf-8").splitlines() if l.strip()]

errors, report = [], []
ids = Counter(q.get("id") for q in questions)
errors += [f"duplicate id {i}" for i, n in ids.items() if n > 1]
filter_values = {f: {p.get(f) for p in pages.values()} for f in config.FILTER_FIELDS}

for q in questions:
    missing = [k for k in REQUIRED if k not in q]
    if missing:
        errors.append(f"{q.get('id')}: missing {missing}")
        continue
    if q["split"] not in ("dev", "test"):
        errors.append(f"{q['id']}: bad split")
    for key, value in (q.get("filter") or {}).items():
        if key not in config.FILTER_FIELDS or value not in filter_values[key]:
            errors.append(f"{q['id']}: filter {key}={value} not a stored metadata value")
    gold = [{"gold_page": q["gold_page"], "evidence_quote": q["evidence_quote"]}] + q.get("alternatives", [])
    checks = []
    for g in gold:
        page = pages.get((q["gold_source_id"], g["gold_page"]))
        found = bool(page) and normalize_for_match(g["evidence_quote"]) in normalize_for_match(page["text"])
        checks.append({"gold_page": g["gold_page"], "found_on_page": found,
                       "page_ip_type": page.get("ip_type") if page else None})
        if not found:
            errors.append(f"{q['id']}: evidence not found on page {g['gold_page']}")
    if q.get("filter") and any(c["page_ip_type"] != q["filter"].get("ip_type") for c in checks[:1]):
        errors.append(f"{q['id']}: gold page does not satisfy its own filter")
    if normalize_for_match(q["evidence_quote"]) in normalize_for_match(q["question"]):
        errors.append(f"{q['id']}: evidence leaked into question text")
    report.append({"id": q["id"], "split": q["split"], "type": q.get("type"),
                   "filter": q.get("filter"), "evidence_checks": checks})

split = Counter(q["split"] for q in questions)
filtered = Counter(q["split"] for q in questions if q.get("filter"))
summary = {
    "questions": len(questions), "split": dict(split),
    "filter_questions": dict(filtered), "types": dict(Counter(q.get("type") for q in questions)),
    "requirements": {
        ">=20 questions": len(questions) >= 20,
        ">=15 dev": split["dev"] >= 15, ">=5 test": split["test"] >= 5,
        ">=3 filter questions": sum(filtered.values()) >= 3, ">=1 filter in test": filtered["test"] >= 1,
    },
    "errors": errors,
    "questions_detail": report,
}
out = config.REPO / "benchmark" / "verification.json"
out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({k: v for k, v in summary.items() if k != "questions_detail"}, indent=2, ensure_ascii=False))
if errors or not all(summary["requirements"].values()):
    sys.exit(1)
print("Benchmark verified.")
