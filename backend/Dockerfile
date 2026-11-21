FROM python:3.12-slim

WORKDIR /app

ENV HERMES_MODEL=deepseek-v4.1-flash \
    HERMES_BASE_URL=https://api-ai.mai.ru/v1 \
    HERMES_REASONING_EFFORT=low

COPY pyproject.toml .
RUN pip install --no-cache-dir "setuptools>=75" wheel
# Install Backend and the Hermes adapter together so pip checks their shared dependencies.
RUN pip install --no-cache-dir --no-build-isolation ".[hermes]" && pip check

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
