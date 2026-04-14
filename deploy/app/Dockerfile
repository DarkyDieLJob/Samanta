# syntax=docker/dockerfile:1.6

FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS base

WORKDIR /app

# Instala dependencias del sistema necesarias para FAISS y watchdog
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY samanta_rag ./samanta_rag

RUN uv sync --all-extras

FROM base AS runtime

WORKDIR /app

COPY --from=base /app/.venv /app/.venv
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

EXPOSE 7860

CMD ["uv", "run", "python", "-m", "samanta_rag.main"]
