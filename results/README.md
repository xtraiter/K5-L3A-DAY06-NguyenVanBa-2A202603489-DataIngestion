# Results

All files are produced by the commands in the root README; nothing here is hand-edited except the three `*_labels.csv` audit files.

| Path | Produced by | Content |
|---|---|---|
| `ingest/page_log.json` | `python -m src.run ingest` | Status of all 201 physical pages (content / excluded / empty), printed page, removed header-footer and endnote line counts |
| `chunks/{A,B,C}.jsonl` | `python -m src.run index` | Every chunk with ID, page, char offsets, section, ip_type, content hash, text (no vectors) |
| `index/index_stats.json` | `index` | Model info, chunk count, char/token distributions, embedding/upsert seconds, upsert counts, re-ingest checks |
| `runs/traces.jsonl` | `python -m src.run evaluate` | 78 traces (26 questions x 3 strategies): question, gold, applied filter, top-3 chunk IDs, text, score, metadata, evidence/page/filter flags |
| `runs/metrics.json`, `runs/metrics.md` | `evaluate` | Hit@1, Evidence Hit@3, page Hit@3, filter compliance by strategy x split, pre-registered selection |
| `audit/coherence_positions.json` | `scripts/make_audit_samples.py` | 10 fixed source positions (rule-based, independent of scores) |
| `audit/*_sample.jsonl` | `make_audit_samples.py` | Material to label: coherence chunks, test top-3 metadata records (with script cross-checks), test top-3 for grounding |
| `audit/coherence_labels.csv` | manual | 0/1/2 + reason for 10 positions x 3 strategies |
| `audit/metadata_labels.csv` | manual + script cross-check | 54 records (6 test questions x top-3 x 3 strategies): source/page/printed page/section/ip_type correctness, filter compliance, notes |
| `audit/grounding_labels.csv` | manual | 0/1/2 + reason for 6 test questions x 3 strategies |
| `audit/grounding_dev_filter_labels.csv` | manual | Supplementary 0/1/2 grounding for dev filter questions q12/q17/q18/q19 (test grounding saturated); not used for selection |
| `audit/audit_summary.{json,md}` | `scripts/summarize_audit.py` | Aggregated audit numbers |

## How the manual labels were made

- **Coherence**: positions = `pages[round(i*(N-1)/9)]`, `char = len(page_text)//2`, i = 0..9, fixed before reading any score. For each strategy, the chunk covering that character (earliest window if two A windows overlap) was read and scored 0 (cut mid-idea / subject missing, not understandable), 1 (partly understandable, missing context), 2 (self-contained, complete idea). C uses exactly the same chunks as B, so its labels are copied from B.
- **Metadata**: `source`, `page` and `printed_page` are cross-checked by script: the chunk text (whitespace removed) must occur in a fresh `pypdf` extraction of that physical page, and printed page = PDF page - 8 for this book. `section` and `ip_type` were checked by reading each chunk against the section heading and chapter. A record counts as correct only if every field is correct.
- **Grounding**: top-3 of each test question read against `expected_answer`: 0 = no evidence, 1 = evidence present but a needed condition/context is missing, 2 = enough to answer and trace to source. This rates retrieved evidence only; no LLM answer was generated.
- **Who labeled**: labels were drafted by the AI assistant (Claude Opus 5.5, used in Claude Code) by reading every chunk listed in the samples; the student (author) is responsible for reviewing and correcting them (review status is stated in the report). Single labeler, not blind to strategy: risk of bias in favour of the expected hypothesis. No LLM-as-judge API call was used; all reasons are written next to each label.
