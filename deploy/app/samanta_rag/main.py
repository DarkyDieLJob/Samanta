"""Punto de entrada de la aplicación Samanta RAG."""

from __future__ import annotations

import uvicorn

from .bootstrap import create_container
from .interface.api.app import create_api_app


_container = create_container()
app = create_api_app(_container)


def main() -> None:
    """Ejecuta el servidor Uvicorn con la aplicación FastAPI."""

    uvicorn.run("samanta_rag.main:app", host="0.0.0.0", port=7860, reload=False)


if __name__ == "__main__":
    main()
