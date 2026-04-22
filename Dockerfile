# Build stage - install dependencies
FROM python:3.14-slim AS builder

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files first for better layer caching
COPY ./uv.lock ./pyproject.toml ./

# Install dependencies in a virtual environment
RUN uv sync --frozen --no-dev --no-cache

# Runtime stage - minimal final image
FROM python:3.14-slim

# Security: run as non-root user
RUN useradd -r -u 1000 -m -s /bin/bash icicle && \
    mkdir /app && \
    chown icicle:icicle /app

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder --chown=icicle:icicle /app/.venv /app/.venv

# Copy application code
COPY --chown=icicle:icicle . .

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONPATH="${PYTHONPATH}:/app/ai-studio" \
    PATH="/app/.venv/bin:$PATH"

# Switch to non-root user
USER icicle

# Expose non-privileged port
EXPOSE 8000

# Health check for container orchestration
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["/app/.venv/bin/python", "-c", "import requests; requests.get('http://localhost:8000/health', timeout=2)"]

# Run FastAPI application
CMD ["fastapi", "run", "ai_studio/main.py", "--port", "8000", "--host", "0.0.0.0"]
