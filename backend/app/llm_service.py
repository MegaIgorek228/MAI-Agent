import json
from typing import Any

import httpx
from openai import OpenAI

from app.config import get_settings


class LLMProviderUnavailable(RuntimeError):
    """Raised when no OpenAI-compatible model endpoint is configured."""


def analyze_document(text: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.llm_base_url or not settings.llm_api_key or not settings.document_model:
        raise LLMProviderUnavailable(
            "Configure LLM_BASE_URL, LLM_API_KEY and DOCUMENT_MODEL for document analysis"
        )
    http_client = httpx.Client(verify=settings.ai_api_ca_bundle or True, timeout=90)
    # MAI relay (2026-11-21): the auth layer rejects any request carrying an
    # `Authorization` header ("Malformed API Key") and only accepts the key in
    # `x-api-key`. openai SDK: api_key="" suppresses the Bearer header
    # (auth_headers property returns {} for an empty key), default_headers
    # carries the real key as x-api-key. Verified live against the relay.
    with OpenAI(
        base_url=settings.llm_base_url,
        api_key="",
        default_headers={"x-api-key": settings.llm_api_key},
        http_client=http_client,
    ) as client:
        response = client.chat.completions.create(
            model=settings.document_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Клиент передаёт текст, который уже извлечён из загруженного документа. "
                        "Проанализируй именно переданный текст. Верни один JSON-объект с полями "
                        "document_type (строка или null), is_readable (логическое), "
                        "extracted_fields (объект) и issues (массив строк). "
                        "Извлекай только явно указанные сведения. Читаемость оценивай "
                        "по разборчивости имеющегося текста, даже если в нём мало полей."
                    ),
                },
                {"role": "user", "content": f"Извлечённый текст документа:\n\n{text}"},
            ],
        )
    content = response.choices[0].message.content if response.choices else None
    if not content:
        raise LLMProviderUnavailable("Model returned an empty document analysis")
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise LLMProviderUnavailable("Model returned a non-object document analysis")
    return parsed
