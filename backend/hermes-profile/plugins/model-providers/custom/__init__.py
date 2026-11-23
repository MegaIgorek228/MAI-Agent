"""MAI-Agent override of the bundled ``custom-provider`` profile
(hermes-agent 0.19.0, container build).

Why: the bundled ``CustomProfile.build_api_kwargs_extras`` projects a
thinking-disabled ``reasoning_config`` as top-level ``reasoning_effort="none"``
plus ``extra_body.think=False``. Auxiliary calls (title generation, smart
approvals) ship disabled reasoning by design, so on the MAI relay
(api-ai.mai.ru, LiteLLM-backed) every such request 400s with:

    Unexpected reasoning effort none. Supported types are xhigh (default),
    medium, and low.

The MAI relay models each accept different reasoning_effort vocabularies:
qwen3.8-27b takes xhigh / medium / low; deepseek-v4.1-flash takes
low / high / xhigh / max / int[1..100] (verified live: "medium" 400s on
DeepSeek V4.1). "none" is rejected by both, so for MAI endpoints this
override projects the disabled state as ``low`` — valid on every relay
model. Every other endpoint keeps the bundled wire shape verbatim.

Scope: this plugin lives in the container Hermes home
(/root/.hermes/plugins/model-providers/custom/) and shadows the bundled plugin
for that home only (documented override path in providers/__init__.py: "user
plugins override bundled plugins on name collision"). The shared hermes-agent
installation is untouched.
"""

from typing import Any
from urllib.parse import urlparse

import os

from providers import register_provider
from providers.base import ProviderProfile
from utils import base_url_host_matches

# The MAI API relay host — the only endpoint where the disabled-reasoning wire
# shape is changed by this override.
MAI_HOST = "api-ai.mai.ru"


# ── MAI relay auth-header fix (2026-11-21) ──────────────────────────────────
# The relay's auth layer now REJECTS any request that carries an
# `Authorization` header (401 "Malformed API Key", identical response to a
# missing key) and accepts the key ONLY in the `x-api-key` header. It worked
# with `Authorization: Bearer` until 2026-11-21 ~17:30 UTC; the relay changed
# auth handling server-side (TLS chain, client certs, and key itself verified
# unchanged: chain fingerprints identical, no mTLS, key accepted via
# x-api-key with a 200 response).
#
# Every Hermes model client goes through the openai SDK, which always emits
# `Authorization: Bearer <api_key>` when api_key is non-empty. The SDK omits
# the header entirely for api_key="" (auth_headers returns {} for an empty
# key). We therefore patch openai.OpenAI/AsyncOpenAI __init__ IN PLACE: for
# MAI base URLs the real key is moved from api_key into
# default_headers["x-api-key"] and api_key is emptied. Patching the class
# object (not a module attribute) reaches every construction path — the
# main-model client and all auxiliary-client factories resolve to the same
# class, regardless of lazy proxies or import timing. Hermes sources are
# untouched; this is profile-layer runtime configuration.
def _install_mai_auth_header_fix() -> None:
    try:
        import openai as _openai_mod
    except Exception:
        return  # openai not importable in this context — nothing to patch

    if getattr(_openai_mod, "_mai_xapikey_patched", False):
        return

    def _rewrite(args: list, kwargs: dict) -> bool:
        base = kwargs.get("base_url")
        if base is None and len(args) > 1:
            base = args[1]
        if "api-ai.mai.ru" not in str(base or ""):
            return False
        key = kwargs.get("api_key")
        if key is None and args:
            key = args[0]
        if not isinstance(key, str) or not key:
            return False
        headers = dict(kwargs.get("default_headers") or {})
        headers["x-api-key"] = key
        kwargs["default_headers"] = headers
        kwargs["api_key"] = ""
        if args:
            args[0] = ""
        return True

    for _cls_name in ("OpenAI", "AsyncOpenAI"):
        _cls = getattr(_openai_mod, _cls_name, None)
        if _cls is None or getattr(_cls, "_mai_xapikey_init", False):
            continue
        _orig_init = _cls.__init__

        def make_patched(orig):
            def _patched_init(self, *args, **kwargs):
                _args = list(args)
                _rewrite(_args, kwargs)
                orig(self, *_args, **kwargs)
            _patched_init._mai_xapikey_init = True
            return _patched_init

        _cls.__init__ = make_patched(_orig_init)

    _openai_mod._mai_xapikey_patched = True


_install_mai_auth_header_fix()


# ── Second chokepoint: httpx transport (2026-11-21) ─────────────────────────
# The named-custom-provider resolution path (used by the vision task router,
# resolve_vision_provider_client → _get_cached_client) builds OpenAI clients
# with api_key="" — the key_env value never reaches the constructor, so the
# __init__ patch above has nothing to move and the request goes out with NO
# auth header at all (relay: 401 "No api key passed in"). Every model HTTP
# call in this process goes through httpx Client/AsyncClient.send, so we fix
# the headers there: for requests to the MAI host, strip any Authorization
# header (the relay 401s on its very presence) and set x-api-key from the
# environment key. Covers SDK clients, vision router clients, and any future
# construction path. Idempotent with the __init__ patch.
def _install_mai_httpx_fix() -> None:
    try:
        import httpx as _httpx_mod
    except Exception:
        return
    if getattr(_httpx_mod, "_mai_httpx_patched", False):
        return

    def _fix_request(request) -> None:
        try:
            url = str(getattr(request, "url", "") or "")
        except Exception:
            return
        if "api-ai.mai.ru" not in url:
            return
        key = (
            os.environ.get("OPENAI_API_KEY", "")
            or os.environ.get("QWEN_API_KEY", "")
        )
        if not key:
            return
        request.headers.pop("Authorization", None)
        request.headers["x-api-key"] = key

    _orig_send = _httpx_mod.Client.send

    def _sync_send(self, request, *args, **kwargs):
        _fix_request(request)
        return _orig_send(self, request, *args, **kwargs)

    _httpx_mod.Client.send = _sync_send

    _orig_asend = _httpx_mod.AsyncClient.send

    async def _async_send(self, request, *args, **kwargs):
        _fix_request(request)
        return await _orig_asend(self, request, *args, **kwargs)

    _httpx_mod.AsyncClient.send = _async_send
    _httpx_mod._mai_httpx_patched = True


_install_mai_httpx_fix()


# ── Third fix: ACP toolset override (2026-11-21, re-scoped 2026-11-23) ───────
# The ACP adapter (acp_adapter/session.py::_make_agent) hardcodes
# enabled_toolsets=["hermes-acp"] and ignores platform_toolsets.acp from
# config.yaml. The stock "hermes-acp" preset is a coding-agent surface.
#
# 2026-11-21: trimmed to session_search only — the model made long filesystem
# detours, the web tools had no paid API keys, and skill_manage triggered a
# slow post-turn background skill review (~100 s model calls).
#
# 2026-11-23: re-scoped to a 10-tool native surface (terminal, files, code,
# memory, session_search, todo) per the product concept.
#
# 2026-11-23 (final, user decision): ALL Hermes functions are enabled. The
# preset is now the FULL tool registry (every tool the installed hermes-agent
# knows, resolved dynamically so future tools are included automatically).
# Tools whose availability requirements are not met in this environment
# (browser without Chromium, x_search without xAI credentials, spotify,
# discord, feishu, homeassistant, yuanbao, kanban, GUI-only project tools,
# ...) are NOT hard errors: each tool's own check_fn marks it unavailable
# for the turn (tools/registry.py: "dependent tools will be unavailable").
# Session MCP tools (fetch_web_page, sql_query, ФИС ГИА) are registered per
# ACP session and are not gated by this toolset — they stay available.
def _install_mai_acp_toolset_override() -> None:
    try:
        import toolsets as _toolsets_mod
    except Exception:
        return
    preset = _toolsets_mod.TOOLSETS.get("hermes-acp")
    if not isinstance(preset, dict):
        return

    def _all_tools() -> list:
        """Full tool registry, resolved at call time (the registry is only
        complete after all tool modules have been imported, which happens
        after plugin load)."""
        try:
            from model_tools import get_all_tool_names

            names = list(get_all_tool_names())
        except Exception:
            names = []
        for name in (
            "terminal", "process",
            "read_file", "write_file", "patch", "search_files",
            "execute_code",
            "memory", "session_search", "todo",
        ):
            if name not in names:
                names.append(name)
        return names

    # Static preset: best available at plugin-load time (fallback for callers
    # that read TOOLSETS['hermes-acp']['tools'] directly).
    preset["tools"] = _all_tools()
    preset["includes"] = []

    # Lazy completion: at session-build time (model_tools._compute_tool
    # definitions → resolve_toolset("hermes-acp")) return the FULL registry
    # so every installed tool is enabled, whatever the plugin-load-time
    # registry state was.
    _orig_resolve = _toolsets_mod.resolve_toolset
    if not getattr(_orig_resolve, "_mai_full_toolset_wrapped", False):

        def _wrapped_resolve(name, visited=None, *, include_registry=True):
            result = list(
                _orig_resolve(name, visited, include_registry=include_registry)
            )
            if name == "hermes-acp":
                try:
                    extra = _all_tools()
                    result = list(dict.fromkeys([*result, *extra]))
                except Exception:
                    pass
            return result

        _wrapped_resolve._mai_full_toolset_wrapped = True
        _toolsets_mod.resolve_toolset = _wrapped_resolve

    # model_tools binds resolve_toolset by name at import time — if it is
    # already imported, rebind the wrapper there too.
    import sys as _sys

    _mt = _sys.modules.get("model_tools")
    if _mt is not None:
        _mt.resolve_toolset = _toolsets_mod.resolve_toolset


_install_mai_acp_toolset_override()


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
        # relay the disabled state is projected as reasoning_effort="low"
        # ("none" 400s; "low" is accepted by every relay model — qwen3.8-27b
        # and deepseek-v4.1-flash, whose vocabularies do not overlap on
        # "medium").
        if reasoning_config and isinstance(reasoning_config, dict):
            _effort = (reasoning_config.get("effort") or "").strip().lower()
            _enabled = reasoning_config.get("enabled", True)
            if _effort == "none" or _enabled is False:
                if base_url_host_matches(str(ctx.get("base_url") or ""), MAI_HOST):
                    top_level["reasoning_effort"] = "low"
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
