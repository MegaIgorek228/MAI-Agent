import math

import httpx
from openai import OpenAI, OpenAIError

from app.config import get_settings


class EmbeddingProviderUnavailable(RuntimeError):
    """Raised when no OpenAI-compatible embedding provider is configured."""


def _client() -> OpenAI:
    settings = get_settings()
    if not settings.embedding_base_url or not settings.embedding_api_key:
        raise EmbeddingProviderUnavailable(
            "Configure EMBEDDING_BASE_URL and EMBEDDING_API_KEY for semantic search"
        )
    http_client = httpx.Client(verify=settings.ai_api_ca_bundle or True, timeout=90)
    # MAI relay (2026-11-21): rejects requests with an `Authorization` header;
    # auth goes via `x-api-key` only. api_key="" makes the openai SDK omit the
    # Bearer header; the real key travels in default_headers (see llm_service).
    return OpenAI(
        base_url=settings.embedding_base_url,
        api_key="",
        default_headers={"x-api-key": settings.embedding_api_key},
        http_client=http_client,
    )


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    settings = get_settings()
    try:
        with _client() as client:
            response = client.embeddings.create(model=settings.embedding_model, input=texts)
    except OpenAIError as exc:
        raise EmbeddingProviderUnavailable("Embedding provider could not process the request") from exc
    entries = sorted(response.data, key=lambda item: item.index)
    if [item.index for item in entries] != list(range(len(texts))):
        raise EmbeddingProviderUnavailable("Embedding provider did not return one vector per input")
    vectors = [item.embedding for item in entries]
    if any(
        len(vector) != settings.embedding_dimensions
        or not all(map(math.isfinite, vector))
        or not any(vector)
        for vector in vectors
    ):
        raise EmbeddingProviderUnavailable("Embedding provider returned an invalid vector")
    return vectors


def embeddings_configured() -> bool:
    settings = get_settings()
    return bool(settings.embedding_base_url and settings.embedding_api_key)
