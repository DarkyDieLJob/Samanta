# syntax=docker/dockerfile:1.6

FROM python:3.11-slim-bookworm AS base

WORKDIR /app

# Instala dependencias del sistema necesarias para FAISS y watchdog
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Instalar uv (gestor de paquetes rápido) y preparar entorno
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && ln -s /root/.local/bin/uv /usr/local/bin/uv
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}:/root/.local/bin"

# Copiar código y metadata de proyecto
COPY pyproject.toml ./
COPY samanta_rag ./samanta_rag

# Resolver e instalar dependencias del proyecto con uv (crea /app/.venv)
RUN uv sync --all-extras

FROM base AS runtime

WORKDIR /app

ENV VIRTUAL_ENV=/app/.venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}:/root/.local/bin"

EXPOSE 7860

CMD ["uv", "run", "python", "-m", "samanta_rag.main"]
