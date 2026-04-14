"""Herramientas de verificación para el sistema RAG."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, Optional

import httpx

from .config import settings
from .constants import METADATA_FILENAME
from .logging_utils import configure_logging

LOGGER = logging.getLogger(__name__)


def verify_vectorstore() -> Dict[str, object]:
    """Comprueba la existencia y consistencia básica del vectorstore."""
    base_path = settings.vectorstore_path
    metadata_file = base_path / METADATA_FILENAME
    summary = {
        "vectorstore_path": str(base_path),
        "metadata_file": str(metadata_file),
        "exists": base_path.exists(),
        "files": 0,
        "chunks": 0,
        "last_updated": None,
        "metadata_valid": False,
    }
    if not base_path.exists():
        LOGGER.error("El directorio del vectorstore %s no existe", base_path)
        return summary
    if not metadata_file.exists():
        LOGGER.error("No se encontró el archivo de metadata %s", metadata_file)
        return summary

    try:
        data = json.loads(metadata_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        LOGGER.error("Metadata inválida en %s: %s", metadata_file, exc)
        return summary

    summary.update(
        {
            "metadata_valid": True,
            "files": len(data),
            "chunks": sum(int(item.get("chunk_count", 0)) for item in data),
            "last_updated": metadata_file.stat().st_mtime,
        }
    )
    LOGGER.info(
        "Vectorstore verificado: %d archivos y %d chunks",
        summary["files"],
        summary["chunks"],
    )
    return summary


async def verify_api(api_url: str, question: Optional[str], timeout: float) -> Dict[str, object]:
    """Invoca los endpoints de salud y, opcionalmente, realiza una consulta de prueba."""
    if api_url.endswith("/"):
        api_url = api_url[:-1]
    async with httpx.AsyncClient(timeout=timeout) as client:
        health_resp = await client.get(f"{api_url}/health")
        health_resp.raise_for_status()
        health_data = health_resp.json()
        LOGGER.info("/health -> %s", health_data)

        status_resp = await client.get(f"{api_url}/api/status")
        status_resp.raise_for_status()
        status_data = status_resp.json()
        LOGGER.info("/api/status -> %s", status_data)

        query_result = None
        if question:
            payload = {"question": question}
            query_resp = await client.post(f"{api_url}/api/query", json=payload)
            query_resp.raise_for_status()
            query_result = query_resp.json()
            LOGGER.info("/api/query -> %s", query_result)

    return {
        "health": health_data,
        "status": status_data,
        "query": query_result,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verificación del despliegue Samanta RAG")
    parser.add_argument(
        "--api-url",
        default="http://localhost:7860",
        help="URL base del servicio FastAPI/Gradio",
    )
    parser.add_argument(
        "--question",
        default=None,
        help="Pregunta de prueba para /api/query",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Timeout en segundos para las solicitudes HTTP",
    )
    parser.add_argument(
        "--skip-api",
        action="store_true",
        help="Omite la verificación de endpoints HTTP",
    )
    return parser.parse_args()


def main() -> None:
    configure_logging(settings.log_path)
    args = parse_args()

    vectorstore_summary = verify_vectorstore()
    LOGGER.info("Resumen vectorstore: %s", vectorstore_summary)

    if not args.skip_api:
        try:
            api_results = asyncio.run(verify_api(args.api_url, args.question, args.timeout))
        except httpx.HTTPError as exc:
            LOGGER.error("Fallo al verificar API: %s", exc)
            return
        LOGGER.info("Resultados API: %s", api_results)


if __name__ == "__main__":
    main()
