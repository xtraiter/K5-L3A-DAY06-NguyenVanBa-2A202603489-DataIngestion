"""Local embedding adapter built on Sentence Transformers.

Default model: intfloat/multilingual-e5-base (768 dims, max 512 tokens).
E5 models expect "query: " / "passage: " prefixes; the adapter adds them so
query vectors stay compatible with document vectors. Errors are raised, never
replaced by mock vectors.
"""
from __future__ import annotations

import os
from typing import Any, Protocol

DEFAULT_MODEL = "intfloat/multilingual-e5-base"

# (query_prefix, document_prefix) required by each model family's model card.
KNOWN_PREFIXES: dict[str, tuple[str, str]] = {
    "intfloat/multilingual-e5-small": ("query: ", "passage: "),
    "intfloat/multilingual-e5-base": ("query: ", "passage: "),
    "intfloat/multilingual-e5-large": ("query: ", "passage: "),
    "BAAI/bge-small-en-v1.5": ("Represent this sentence for searching relevant passages: ", ""),
    "BAAI/bge-base-en-v1.5": ("Represent this sentence for searching relevant passages: ", ""),
}


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class LocalEmbedder:
    """Sentence Transformers model running on this machine (GPU if available)."""

    def __init__(self, model_name: str | None = None, device: str | None = None,
                 batch_size: int = 32) -> None:
        # Imported here so a missing install fails loudly with a clear message.
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed; see starter/README.md section 2."
            ) from exc

        self.model_name = model_name or os.getenv("EMBEDDING_MODEL") or DEFAULT_MODEL
        device = device or os.getenv("EMBEDDING_DEVICE") or None  # None = auto (cuda if available)
        self.batch_size = batch_size

        self._model = SentenceTransformer(self.model_name, device=device)
        get_dim = getattr(self._model, "get_sentence_embedding_dimension", None) \
            or self._model.get_embedding_dimension
        self.dimensions: int = int(get_dim())
        self.max_seq_length: int = int(self._model.max_seq_length)
        self.device = str(self._model.device)

        if self.model_name in KNOWN_PREFIXES:
            self.query_prefix, self.document_prefix = KNOWN_PREFIXES[self.model_name]
        elif "e5" in self.model_name.lower():
            self.query_prefix, self.document_prefix = "query: ", "passage: "
        else:
            self.query_prefix, self.document_prefix = "", ""

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,  # unit vectors: cosine similarity == dot product
            convert_to_numpy=True,
            show_progress_bar=len(texts) > self.batch_size,
        )
        if len(vectors) != len(texts) or vectors.shape[1] != self.dimensions:
            raise RuntimeError(
                f"Embedding shape mismatch: got {vectors.shape}, "
                f"expected ({len(texts)}, {self.dimensions})"
            )
        return vectors.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._encode([self.document_prefix + t for t in texts])

    def embed_query(self, question: str) -> list[float]:
        return self._encode([self.query_prefix + question])[0]

    def token_lengths(self, texts: list[str], as_document: bool = True) -> list[int]:
        """Token count per text (prefix included) to detect silent truncation."""
        prefix = self.document_prefix if as_document else self.query_prefix
        tokenizer = self._model.tokenizer
        return [len(tokenizer(prefix + t, add_special_tokens=True)["input_ids"]) for t in texts]

    def info(self) -> dict[str, Any]:
        """Settings to record in the report and experiment log."""
        import sentence_transformers
        import torch

        return {
            "provider": "local/sentence-transformers",
            "model": self.model_name,
            "dimensions": self.dimensions,
            "max_seq_length": self.max_seq_length,
            "query_prefix": self.query_prefix,
            "document_prefix": self.document_prefix,
            "normalized": True,
            "device": self.device,
            "sentence_transformers": sentence_transformers.__version__,
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "cost_usd": 0,
        }
