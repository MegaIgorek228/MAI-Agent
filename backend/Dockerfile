FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir "setuptools>=75" wheel
RUN pip install --no-cache-dir --no-build-isolation ".[test]"
# fastmcp>=2,<3 resolves to 2.5.2 in this image (2.14.x fails dependency
# resolution here), and 2.5.2's ServerSettings crashes pydantic 2.13 at import
# ("cannot specify both default and default_factory") -> app.main fails to load.
# Pin the version proven in the working host environment (fastmcp 2.14.7 +
# pydantic 2.13.x, where the full 19-test suite passes).
RUN pip install --no-cache-dir --retries 5 --timeout 120 "fastmcp==2.14.7"
RUN pip install --no-cache-dir --retries 5 --timeout 120 "hermes-agent==0.19.0"
# The ACP adapter shipped in hermes-agent 0.19.0 imports ModelInfo from acp.schema.
# ModelInfo was REMOVED from acp.schema starting with 0.10.x and is absent in every
# release 0.10.0..1.0.0 (verified by scanning wheels: 0.11.0/0.11.1/0.12.0/0.12.1/
# 1.0.0rc1-3/1.0.0 — none contain it). 0.9.0 is the newest release that still
# provides ModelInfo AND everything the backend imports (HttpHeader, HttpMcpServer,
# ImageContentBlock, TextContentBlock, connect_to_agent, PROTOCOL_VERSION=1) — the
# same version the working host-side PM venv uses. Verified in-container:
# hermes-agent 0.19.0 + acp 0.9.0 -> acp_adapter.entry/server import OK.
# Without this pin the in-container hermes-acp crashes at startup (ImportError)
# and no ACP session can start.
RUN pip install --no-cache-dir --retries 5 --timeout 120 "agent-client-protocol==0.9.0"

# Container Hermes home: model/provider config + the custom-provider override
# (MAI relay reasoning fix). No secrets — the key arrives via the OPENAI_API_KEY
# env var (compose). Without this the in-container hermes-acp falls back to the
# default openrouter provider and every model call fails.
COPY hermes-profile /root/.hermes

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
