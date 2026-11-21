import json
from typing import Any

import httpx
from openai import OpenAI

from app.config import get_settings


class LLMProviderUnavailable(RuntimeError):
    """Raised when no OpenAI-compatible Qwen endpoint is configured."""


def analyze_document(text: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.qwen_base_url or not settings.qwen_api_key or not settings.qwen_model:
        raise LLMProviderUnavailable(
            "Configure QWEN_BASE_URL, QWEN_API_KEY and QWEN_MODEL for document analysis"
        )
    http_client = httpx.Client(verify=settings.ai_api_ca_bundle or True, timeout=90)
    client = OpenAI(
        base_url=settings.qwen_base_url,
        api_key=settings.qwen_api_key,
        http_client=http_client,
    )
    response = client.chat.completions.create(
        model=settings.qwen_model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You analyze applicant documents. Return only JSON with keys "
                    "document_type, is_readable, extracted_fields, issues. "
                    "Do not invent values; use null or an empty list when unknown."
                ),
            },
            {"role": "user", "content": text},
        ],
    )
    content = response.choices[0].message.content
    if not content:
        raise LLMProviderUnavailable("Qwen returned an empty document analysis")
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise LLMProviderUnavailable("Qwen returned a non-object document analysis")
    return parsed
