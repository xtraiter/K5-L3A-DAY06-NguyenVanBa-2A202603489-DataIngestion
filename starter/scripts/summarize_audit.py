"""Aggregate the manual audit labels in results/audit/*.csv into audit_summary.{json,md}.

Run from starter/:  python scripts/summarize_audit.py
"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config  # noqa: E402

AUDIT = config.RESULTS / "audit"


def read(name):
    with (AUDIT / name).open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


coh, meta, grd = read("coherence_labels.csv"), read("metadata_labels.csv"), read("grounding_labels.csv")
summary = {}
for s in config.STRATEGIES:
    c = [int(r["score"]) for r in coh if r["strategy"] == s]
    m = [r for r in meta if r["strategy"] == s]
    f = [r for r in m if r["question_filter"]]
    fq = {}
    for r in f:
        fq.setdefault(r["id"], []).append(r["filter_ok"] == "True")
    g = [int(r["score"]) for r in grd if r["strategy"] == s]
    gc = Counter(g)
    summary[s] = {
        "coherence": {"n": len(c), "sum": sum(c), "mean_of_2": round(sum(c) / len(c), 2),
                      "counts": {k: Counter(c)[k] for k in (0, 1, 2)}},
        "metadata": {"records_checked": len(m), "all_correct": sum(r["all_correct"] == "True" for r in m),
                     "errors": [f"{r['id']} r{r['rank']}: {r['note']}" for r in m if r["all_correct"] != "True"]},
        "filter_compliance_test": {"questions_with_filter": len(fq),
                                   "top3_compliant": sum(all(v) for v in fq.values()),
                                   "records_compliant": sum(r["filter_ok"] == "True" for r in f),
                                   "records": len(f)},
        "grounding": {"n": len(g), "counts": {k: gc[k] for k in (0, 1, 2)},
                      "mean_of_2": round(sum(g) / len(g), 2)},
    }
extra = AUDIT / "grounding_dev_filter_labels.csv"
if extra.exists():  # supplementary, dev filter questions only; not used for selection
    rows = read(extra.name)
    for s in config.STRATEGIES:
        g = [int(r["score"]) for r in rows if r["strategy"] == s]
        summary[s]["grounding_dev_filter_supplementary"] = {
            "n": len(g), "counts": {k: Counter(g)[k] for k in (0, 1, 2)},
            "mean_of_2": round(sum(g) / len(g), 2)}

(AUDIT / "audit_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

lines = ["| Strategy | Coherence mean /2 (n) | Metadata correct (n/N) | Filter compliant top-3, test (n/N) "
         "| Grounding 0/1/2 | Grounding mean /2 |", "|---|---|---|---|---|---|"]
for s, v in summary.items():
    fc = v["filter_compliance_test"]
    lines.append(f"| {s} | {v['coherence']['mean_of_2']} ({v['coherence']['n']}) | "
                 f"{v['metadata']['all_correct']}/{v['metadata']['records_checked']} | "
                 f"{fc['top3_compliant']}/{fc['questions_with_filter']} | "
                 f"{v['grounding']['counts'][0]}/{v['grounding']['counts'][1]}/{v['grounding']['counts'][2]} | "
                 f"{v['grounding']['mean_of_2']} |")
if extra.exists():
    lines += ["", "Supplementary grounding, dev filter questions q12/q17/q18/q19 (not used for selection):", "",
              "| Strategy | 0/1/2 | Mean /2 |", "|---|---|---|"]
    for s, v in summary.items():
        g = v["grounding_dev_filter_supplementary"]
        lines.append(f"| {s} | {g['counts'][0]}/{g['counts'][1]}/{g['counts'][2]} | {g['mean_of_2']} |")
(AUDIT / "audit_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
