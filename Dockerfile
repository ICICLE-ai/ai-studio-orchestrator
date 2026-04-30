# Build stage - install dependencies.
FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY ./uv.lock ./pyproject.toml ./
RUN uv sync --frozen --no-dev --no-cache

# Runtime stage - minimal final image.
FROM python:3.14-slim

RUN useradd -r -u 1000 -m -s /bin/bash icicle \
    && mkdir /app \
    && chown icicle:icicle /app

WORKDIR /app
COPY --from=builder --chown=icicle:icicle /app/.venv /app/.venv
COPY --chown=icicle:icicle . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PATH="/app/.venv/bin:$PATH"

USER icicle
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["/app/.venv/bin/python", "-c", "from urllib.request import urlopen; urlopen('http://localhost:8000/health', timeout=2).read()"]

CMD ["fastapi", "run", "ai_studio/main.py", "--port", "8000", "--host", "0.0.0.0"]
