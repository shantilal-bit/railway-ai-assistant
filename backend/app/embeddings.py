"""Cloudflare Workers AI Multilingual Embedding Client (@cf/baai/bge-m3, 1024 dimensions)."""

from __future__ import annotations

import asyncio
import math
import os
from typing import Sequence

import httpx

BGE_M3_MODEL = "@cf/baai/bge-m3"
BGE_M3_DIMENSIONS = 1024
DEFAULT_BATCH_SIZE = 16
MAX_RETRIES = 3


class EmbeddingError(RuntimeError):
    """Raised when Cloudflare Workers AI embedding generation or validation fails."""


class EmbeddingDimensionError(EmbeddingError):
    """Raised when returned embedding vectors do not match the expected 1024 dimensions."""


def resolve_cloudflare_account_id() -> str:
    account_id = (
        os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
        or os.getenv("R2_ACCOUNT_ID", "").strip()
    )
    if not account_id:
        raise EmbeddingError(
            "Missing CLOUDFLARE_ACCOUNT_ID (or R2_ACCOUNT_ID fallback) environment variable."
        )
    return account_id


def resolve_cloudflare_api_token() -> str:
    token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    if not token:
        raise EmbeddingError("Missing CLOUDFLARE_API_TOKEN environment variable.")
    return token


def validate_embedding_vector(vector: object, expected_dim: int = BGE_M3_DIMENSIONS) -> list[float]:
    if not isinstance(vector, (list, tuple)):
        raise EmbeddingDimensionError("Embedding vector is not a JSON array.")
    if len(vector) != expected_dim:
        raise EmbeddingDimensionError(
            f"Expected {expected_dim}-dimensional BGE-M3 embedding, got {len(vector)}."
        )
    cleaned: list[float] = []
    for val in vector:
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise EmbeddingDimensionError("Embedding vector contains non-numeric entries.")
        f = float(val)
        if not math.isfinite(f):
            raise EmbeddingDimensionError("Embedding vector contains NaN or Infinity.")
        cleaned.append(f)
    return cleaned


class CloudflareBgeM3Embedder:
    """Calls Cloudflare Workers AI REST API for @cf/baai/bge-m3 with batching, retries, and 1024-dim validation."""

    def __init__(
        self,
        account_id: str | None = None,
        api_token: str | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_retries: int = MAX_RETRIES,
        timeout_seconds: float = 45.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.account_id = (account_id or resolve_cloudflare_account_id()).strip()
        self.api_token = (api_token or resolve_cloudflare_api_token()).strip()
        self.batch_size = max(1, batch_size)
        self.max_retries = max(1, max_retries)
        self.timeout_seconds = timeout_seconds
        self._external_client = client

    @property
    def endpoint_url(self) -> str:
        return (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{self.account_id}/ai/run/{BGE_M3_MODEL}"
        )

    async def embed_query(self, query_text: str) -> list[float]:
        cleaned = (query_text or "").strip()
        if not cleaned:
            raise EmbeddingError("Cannot compute embedding for empty query text.")
        vectors = await self.embed_texts([cleaned])
        return vectors[0]

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        normalized = [t.strip() for t in texts]
        if not normalized:
            return []
        if any(not t for t in normalized):
            raise EmbeddingError("Batch contains empty text; cannot compute BGE-M3 embedding.")

        all_vectors: list[list[float]] = []
        if self._external_client is not None:
            for i in range(0, len(normalized), self.batch_size):
                batch = normalized[i : i + self.batch_size]
                all_vectors.extend(await self._embed_batch_with_retry(self._external_client, batch))
        else:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                for i in range(0, len(normalized), self.batch_size):
                    batch = normalized[i : i + self.batch_size]
                    all_vectors.extend(await self._embed_batch_with_retry(client, batch))
        return all_vectors

    async def _embed_batch_with_retry(
        self,
        client: httpx.AsyncClient,
        batch: list[str],
    ) -> list[list[float]]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = await client.post(
                    self.endpoint_url,
                    headers={
                        "Authorization": f"Bearer {self.api_token}",
                        "Content-Type": "application/json",
                    },
                    json={"text": batch},
                )
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    await asyncio.sleep(min(8.0, 0.75 * (2 ** (attempt - 1))))
                    continue

                if resp.status_code >= 400:
                    # Do NOT echo tokens or large bodies into logs/errors
                    raise EmbeddingError(
                        f"Cloudflare BGE-M3 API returned HTTP {resp.status_code}."
                    )

                payload = resp.json()
                if not isinstance(payload, dict) or payload.get("success") is False:
                    errors = payload.get("errors") if isinstance(payload, dict) else None
                    err_code = errors[0].get("code") if isinstance(errors, list) and errors else None
                    raise EmbeddingError(
                        f"Cloudflare BGE-M3 API reported failure (code={err_code})."
                    )

                result = payload.get("result") or {}
                raw_vectors = result.get("data")
                if not isinstance(raw_vectors, list) or len(raw_vectors) != len(batch):
                    raise EmbeddingError(
                        f"Cloudflare BGE-M3 returned {len(raw_vectors) if isinstance(raw_vectors, list) else 0} "
                        f"vectors for batch size {len(batch)}."
                    )

                return [validate_embedding_vector(v, BGE_M3_DIMENSIONS) for v in raw_vectors]

            except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    await asyncio.sleep(min(8.0, 0.75 * (2 ** (attempt - 1))))
                    continue
                raise EmbeddingError(f"Cloudflare BGE-M3 network error: {exc.__class__.__name__}") from exc
            except EmbeddingError:
                raise
            except Exception as exc:
                last_error = exc
                raise EmbeddingError(f"Unexpected embedding error: {exc.__class__.__name__}") from exc

        raise EmbeddingError(f"Cloudflare BGE-M3 failed after {self.max_retries} attempts: {last_error}")
