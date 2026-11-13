"""Smoke test for the local embedder: loads the model, prints settings and a sanity check.

Run from starter/:  python scripts/check_embedder.py
This checks setup only; it is not a benchmark result.
"""
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.embeddings import LocalEmbedder  # noqa: E402

start = time.perf_counter()
embedder = LocalEmbedder()
print(f"Loaded in {time.perf_counter() - start:.1f}s")
print(json.dumps(embedder.info(), indent=2, ensure_ascii=False))

query = "Hạn nộp hồ sơ là khi nào?"
passages = [
    "Hạn nộp hồ sơ là ngày 30 tháng 6.",
    "Thư viện mở cửa từ 8 giờ sáng đến 9 giờ tối.",
]
q = embedder.embed_query(query)
docs = embedder.embed_documents(passages)
scores = [sum(a * b for a, b in zip(q, d)) for d in docs]
for passage, score in zip(passages, scores):
    print(f"cosine={score:.4f}  {passage}")

if len(q) != embedder.dimensions:
    sys.exit("Query vector has wrong dimensions.")
if scores[0] <= scores[1]:
    sys.exit("Sanity check failed: relevant passage did not score higher.")
print("Embedder OK.")
