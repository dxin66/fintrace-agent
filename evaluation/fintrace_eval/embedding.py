"""Cached OpenAI-compatible embeddings for reproducible retrieval experiments."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import httpx


class CachedEmbeddingClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int,
        cache_path: str | Path,
        batch_size: int = 10,
        timeout_seconds: float = 120,
    ) -> None:
        if not api_key:
            raise ValueError("embedding API key is empty")
        if dimensions <= 0 or batch_size <= 0:
            raise ValueError("dimensions and batch_size must be positive")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.timeout_seconds = timeout_seconds
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.cache_path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS embeddings (
                cache_key TEXT PRIMARY KEY,
                model TEXT NOT NULL,
                dimensions INTEGER NOT NULL,
                text_sha256 TEXT NOT NULL,
                vector_json TEXT NOT NULL
            )
            """
        )
        self.connection.commit()
        self.request_count = 0
        self.cache_hits = 0
        self.cache_misses = 0

    def __enter__(self) -> "CachedEmbeddingClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def _cache_key(self, text: str) -> tuple[str, str]:
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        raw_key = f"{self.model}\0{self.dimensions}\0{text_hash}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest(), text_hash

    def _read_cached(self, keys: list[str]) -> dict[str, list[float]]:
        if not keys:
            return {}
        result: dict[str, list[float]] = {}
        for start in range(0, len(keys), 500):
            block = keys[start : start + 500]
            placeholders = ",".join("?" for _ in block)
            rows = self.connection.execute(
                f"SELECT cache_key, vector_json FROM embeddings WHERE cache_key IN ({placeholders})",
                block,
            )
            result.update({key: json.loads(vector) for key, vector in rows})
        return result

    def _request(self, texts: list[str]) -> list[list[float]]:
        response = httpx.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts, "dimensions": self.dimensions},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        rows = sorted(response.json()["data"], key=lambda row: row["index"])
        vectors = [row["embedding"] for row in rows]
        if len(vectors) != len(texts):
            raise RuntimeError(
                f"embedding count mismatch: requested {len(texts)}, received {len(vectors)}"
            )
        if any(len(vector) != self.dimensions for vector in vectors):
            raise RuntimeError(
                "embedding provider returned an unexpected vector dimension"
            )
        self.request_count += 1
        return vectors

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        keys_and_hashes = [self._cache_key(text) for text in texts]
        keys = [key for key, _ in keys_and_hashes]
        cached = self._read_cached(list(dict.fromkeys(keys)))
        self.cache_hits += sum(key in cached for key in keys)

        missing_by_key: dict[str, tuple[str, str]] = {}
        for text, (key, text_hash) in zip(texts, keys_and_hashes):
            if key not in cached:
                missing_by_key.setdefault(key, (text, text_hash))
        missing_items = list(missing_by_key.items())
        self.cache_misses += len(missing_items)

        for start in range(0, len(missing_items), self.batch_size):
            batch = missing_items[start : start + self.batch_size]
            batch_vectors = self._request([item[1][0] for item in batch])
            rows = []
            for (key, (_, text_hash)), vector in zip(batch, batch_vectors):
                cached[key] = vector
                rows.append(
                    (
                        key,
                        self.model,
                        self.dimensions,
                        text_hash,
                        json.dumps(vector, separators=(",", ":")),
                    )
                )
            self.connection.executemany(
                "INSERT OR REPLACE INTO embeddings VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            self.connection.commit()
        return [cached[key] for key in keys]

    def stats(self) -> dict[str, int | str]:
        return {
            "model": self.model,
            "dimensions": self.dimensions,
            "batch_size": self.batch_size,
            "request_count": self.request_count,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
        }
