"""Download the corpus PDF (CC BY 4.0) and verify its SHA-256 against the manifest snapshot.

Run from starter/:  python scripts/download_corpus.py
"""
import hashlib
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import RAW_PDF, SOURCE  # noqa: E402

if not RAW_PDF.exists():
    RAW_PDF.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {SOURCE['source_path_or_url']}")
    urllib.request.urlretrieve(SOURCE["source_path_or_url"], RAW_PDF)

digest = hashlib.sha256(RAW_PDF.read_bytes()).hexdigest()
print(f"{RAW_PDF.name}  sha256={digest}")
if digest != SOURCE["sha256"]:
    sys.exit("SHA-256 differs from the snapshot used in this lab: OpenStax may have updated the PDF. "
             "Page numbers in the benchmark refer to the recorded snapshot.")
print("Corpus OK.")
