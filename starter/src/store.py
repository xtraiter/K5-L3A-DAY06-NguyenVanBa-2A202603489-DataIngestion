"""PostgreSQL + pgvector store: one table, rows keyed by (strategy, chunk_id).

Search is exact (sequential scan, no ANN index) with cosine distance `<=>`, so a
metadata filter never reduces the number of returned rows below top_k.
"""
from __future__ import annotations

import json
from typing import Any

import psycopg

from .models import Chunk

FILTERABLE_COLUMNS = {"ip_type", "chapter", "section", "document_id"}


def _vec(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.7f}" for v in values) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL is empty; copy starter/.env.example to starter/.env")
        if not isinstance(dimensions, int) or dimensions <= 0:
            raise ValueError("dimensions must be a positive int")
        self.database_url = database_url
        self.dimensions = dimensions

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, connect_timeout=5)

    def create_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS chunks (
                    strategy      text    NOT NULL,
                    chunk_id      text    NOT NULL,
                    document_id   text    NOT NULL,
                    source        text    NOT NULL,
                    page          integer NOT NULL,
                    printed_page  integer,
                    chapter       integer,
                    ip_type       text,
                    section       text,
                    section_title text,
                    text          text    NOT NULL,
                    content_hash  text    NOT NULL,
                    model         text    NOT NULL,
                    metadata      jsonb   NOT NULL,
                    embedding     vector({self.dimensions}) NOT NULL,
                    updated_at    timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (strategy, chunk_id)
                )""")
            conn.execute("CREATE INDEX IF NOT EXISTS chunks_strategy_ip_type ON chunks (strategy, ip_type)")
            row = conn.execute(
                "SELECT atttypmod FROM pg_attribute WHERE attrelid = 'chunks'::regclass "
                "AND attname = 'embedding'").fetchone()
            if row and row[0] != self.dimensions:
                raise RuntimeError(f"Existing table has vector({row[0]}), model gives {self.dimensions}")

    def existing(self, strategy: str) -> dict[str, tuple[str, str]]:
        """chunk_id -> (content_hash, model) currently stored for a strategy."""
        with self._connect() as conn:
            rows = conn.execute("SELECT chunk_id, content_hash, model FROM chunks WHERE strategy = %s",
                                (strategy,)).fetchall()
        return {r[0]: (r[1], r[2]) for r in rows}

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]],
               model: str = "unknown") -> dict[str, int]:
        """Insert new chunks, update changed ones, delete obsolete chunks of the same documents.

        `vectors[i]` may be None for a chunk whose stored hash+model are unchanged (skipped).
        Returns counts {inserted, updated, unchanged, deleted}.
        """
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        ids = [c.chunk_id for c in chunks]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate chunk_id in batch")
        counts = {"inserted": 0, "updated": 0, "unchanged": 0, "deleted": 0}
        with self._connect() as conn, conn.cursor() as cur:
            for chunk, vector in zip(chunks, vectors):
                if vector is None:
                    counts["unchanged"] += 1
                    continue
                if len(vector) != self.dimensions:
                    raise ValueError(f"{chunk.chunk_id}: vector has {len(vector)} dims, expected {self.dimensions}")
                m = chunk.metadata
                cur.execute("""
                    INSERT INTO chunks (strategy, chunk_id, document_id, source, page, printed_page,
                        chapter, ip_type, section, section_title, text, content_hash, model,
                        metadata, embedding)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)
                    ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                        document_id = EXCLUDED.document_id, source = EXCLUDED.source,
                        page = EXCLUDED.page, printed_page = EXCLUDED.printed_page,
                        chapter = EXCLUDED.chapter, ip_type = EXCLUDED.ip_type,
                        section = EXCLUDED.section, section_title = EXCLUDED.section_title,
                        text = EXCLUDED.text, content_hash = EXCLUDED.content_hash,
                        model = EXCLUDED.model, metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding, updated_at = now()
                    RETURNING (xmax = 0)""",
                    (strategy, chunk.chunk_id, chunk.document_id, chunk.source, chunk.page,
                     m.get("printed_page"), m.get("chapter"), m.get("ip_type"), m.get("section"),
                     m.get("section_title"), chunk.text, m["content_hash"], model,
                     json.dumps(m, ensure_ascii=False), _vec(vector)))
                counts["inserted" if cur.fetchone()[0] else "updated"] += 1
            docs = sorted({c.document_id for c in chunks})
            cur.execute("DELETE FROM chunks WHERE strategy = %s AND document_id = ANY(%s) "
                        "AND NOT (chunk_id = ANY(%s))", (strategy, docs, ids))
            counts["deleted"] = cur.rowcount
        return counts

    def count(self, strategy: str | None = None) -> int:
        with self._connect() as conn:
            if strategy is None:
                return conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
            return conn.execute("SELECT count(*) FROM chunks WHERE strategy = %s", (strategy,)).fetchone()[0]

    def delete_strategy(self, strategy: str) -> int:
        with self._connect() as conn:
            return conn.execute("DELETE FROM chunks WHERE strategy = %s", (strategy,)).rowcount

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if len(query_vector) != self.dimensions:
            raise ValueError("query vector has wrong dimensions")
        where, params = ["strategy = %s"], [strategy]
        for key, value in (filters or {}).items():
            if key not in FILTERABLE_COLUMNS:
                raise ValueError(f"filter on {key!r} not allowed")
            where.append(f"{key} = %s")  # column name from allow-list, value parameterized
            params.append(value)
        qv = _vec(query_vector)
        sql = (f"SELECT chunk_id, document_id, source, page, printed_page, chapter, ip_type, section, "
               f"section_title, text, metadata, 1 - (embedding <=> %s::vector) AS score "
               f"FROM chunks WHERE {' AND '.join(where)} "
               f"ORDER BY embedding <=> %s::vector, chunk_id LIMIT %s")
        with self._connect() as conn:
            rows = conn.execute(sql, [qv, *params, qv, top_k]).fetchall()
        keys = ["chunk_id", "document_id", "source", "page", "printed_page", "chapter", "ip_type",
                "section", "section_title", "text", "metadata", "score"]
        return [dict(zip(keys, r)) | {"rank": i + 1} for i, r in enumerate(rows)]
