"""MAI-Agent override of the bundled ``custom-provider`` profile
(hermes-agent 0.19.0, container build).

Why: the bundled ``CustomProfile.build_api_kwargs_extras`` projects a
thinking-disabled ``reasoning_config`` as top-level ``reasoning_effort="none"``
plus ``extra_body.think=False``. Auxiliary calls (title generation, smart
approvals) ship disabled reasoning by design, so on the MAI relay
(api-ai.mai.ru, LiteLLM-backed) every such request 400s with:

    Unexpected reasoning effort none. Supported types are xhigh (default),
    medium, and low.

The MAI relay only accepts xhigh / medium / low. For MAI endpoints this
override projects the disabled state as ``medium`` (a supported level). Every
other endpoint keeps the bundled wire shape verbatim.

Scope: this plugin lives in the container Hermes home
(/root/.hermes/plugins/model-providers/custom/) and shadows the bundled plugin
for that home only (documented override path in providers/__init__.py: "user
plugins override bundled plugins on name collision"). The shared hermes-agent
installation is untouched.
"""

from typing import Any
from urllib.parse import urlparse

from providers import register_provider
from providers.base import ProviderProfile
from utils import base_url_host_matches

# The MAI API relay host — the only endpoint where the disabled-reasoning wire
# shape is changed by this override.
MAI_HOST = "api-ai.mai.ru"


def _looks_like_ollama_endpoint(base_url: str | None) -> bool:
    """True only for explicit Ollama signatures (port 11434 or an ``ollama`` host label)."""
    raw = (base_url or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    try:
        if parsed.port == 11434:
            return True
    except ValueError:
        pass
    host = (parsed.hostname or "").lower().rstrip(".")
    return bool(host) and (host == "ollama.com" or host.endswith(".ollama.com") or "ollama" in host.split("."))


class CustomProfile(ProviderProfile):
    """Custom/Ollama local provider — think=false and num_ctx support, with the
    MAI-relay disabled-reasoning fix (see module docstring)."""

    def build_api_kwargs_extras(
        self,
        *,
        reasoning_config: dict | None = None,
        ollama_num_ctx: int | None = None,
        **ctx: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        extra_body: dict[str, Any] = {}
        top_level: dict[str, Any] = {}

        # Ollama context window
        if ollama_num_ctx:
            options = extra_body.get("options", {})
            options["num_ctx"] = ollama_num_ctx
            extra_body["options"] = options

        # Reasoning / thinking control for custom OpenAI-compatible endpoints.
        # Same wire shapes as the bundled 0.19.0 profile, except: on the MAI
        # relay the disabled state is projected as reasoning_effort="medium"
        # (the relay 400s on "none"; it accepts xhigh/medium/low).
        if reasoning_config and isinstance(reasoning_config, dict):
            _effort = (reasoning_config.get("effort") or "").strip().lower()
            _enabled = reasoning_config.get("enabled", True)
            if _effort == "none" or _enabled is False:
                if base_url_host_matches(str(ctx.get("base_url") or ""), MAI_HOST):
                    top_level["reasoning_effort"] = "medium"
                else:
                    top_level["reasoning_effort"] = "none"
                    if _looks_like_ollama_endpoint(ctx.get("base_url")):
                        extra_body["think"] = False
            elif _effort:
                top_level["reasoning_effort"] = _effort

        return extra_body, top_level

    def fetch_models(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 8.0,
    ) -> list[str] | None:
        """Custom/Ollama: base_url is user-configured; fetch if set."""
        if not (base_url or self.base_url):
            return None
        return super().fetch_models(api_key=api_key, base_url=base_url, timeout=timeout)


custom = CustomProfile(
    name="custom",
    aliases=(
        "ollama",
        "local",
        "vllm",
        "llamacpp",
        "llama.cpp",
        "llama-cpp",
    ),
    env_vars=(),  # No fixed key — custom endpoint
    base_url="",  # User-configured
    default_max_tokens=65536,
)

register_provider(custom)
