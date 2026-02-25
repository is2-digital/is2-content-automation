# syntax=docker/dockerfile:1

# ============================================================
# Base stage: shared between dev and prod
# ============================================================
FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies needed by asyncpg and other native extensions
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq-dev \
        gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy only dependency metadata first for layer caching
COPY pyproject.toml ./

# ============================================================
# Dev stage: hot reload, debug tools, dev dependencies
# ============================================================
FROM base AS dev

ENV ENVIRONMENT=development

# Copy full source first — editable install requires the package directory
COPY . .

# Install the project with dev dependencies in editable mode
RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8000

# Run with uvicorn reload for hot-reloading during development
CMD ["uvicorn", "ica.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ============================================================
# Builder stage: install production dependencies in isolation
# ============================================================
FROM base AS builder

# Install production dependencies into a virtual env for clean copy
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml ./
COPY ica/ ./ica/
RUN pip install --no-cache-dir .

# ============================================================
# Prod stage: slim runtime image with no dev tooling
# ============================================================
FROM python:3.12-slim AS prod

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Install only the minimal runtime library (no gcc/dev headers)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy the pre-built virtual env from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application source
COPY ica/ ./ica/

# Create non-root user for security
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

# Run with gunicorn + uvicorn workers for production
CMD ["gunicorn", "ica.app:create_app()", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--access-logfile", "-"]
