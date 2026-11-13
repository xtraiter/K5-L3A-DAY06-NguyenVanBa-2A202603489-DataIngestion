# Benchmark

Written and verified **before any retrieval run** (see git history: this folder is committed before `results/runs/`).

| File | Content |
|---|---|
| `questions.jsonl` | 26 questions with gold page, evidence quote, alternatives, filter |
| `verification.json` | Output of `python scripts/verify_benchmark.py`: every evidence quote found on its gold page after normalization |

## Fields

`id`, `split`, `type`, `question`, `expected_answer`, `gold_source_id`, `gold_page` (1-based physical PDF page), `gold_section`, `evidence_quote`, `alternatives` (other valid page + quote pairs, any of which counts as a hit), `filter` (`null` or `{"ip_type": ...}`), `filter_context`.

## Split (fixed before running)

- **Dev: 20** questions (q01-q20). **Test: 6** questions (q21-q26).
- Split by **section** to limit leakage: test questions come only from sections 1.7, 2.9, 3.5, 4.6, 4.9, 5.3; no dev question uses these sections as its gold section.
- Types: direct 7, paraphrase 4, condition 4, exception 3, metadata_filter 6, cross_lingual (Vietnamese question, English corpus) 2.
- **Metadata filter questions: 6** (dev q12, q17, q18, q19; test q23, q25). The filter value (`ip_type`) is supplied by user context before retrieval ("learner is browsing module X"); the question text deliberately does not name the IP type, because the same question has different answers in different chapters (e.g. fair use exists for both copyright 3.7 and trademark 4.11; protection term differs for patent, copyright and trade secret).
- Remaining leakage risk: dev and test filter questions share a pattern (e.g. "how long does protection last" for trade secret in dev, for copyright in test). Alternative evidence of q23 sits on page 102 (section 3.1), the gold section of dev q11.

## Evidence rule

A retrieved chunk is an evidence hit when it belongs to the gold source and a gold/alternative page, and contains the **full** evidence quote (comparison after NFKC, quote/whitespace normalization, lower-case). Questions without an answer in the source are not used.

## Strategy selection criterion (pre-registered)

Chosen on **dev only**, before looking at test:
1. highest dev Evidence Hit@3;
2. tie: highest dev Hit@1;
3. tie: fewer chunks / lower indexing time.

Test is run once on the fixed configurations and reported separately.
