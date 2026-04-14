"""Construcción de la aplicación FastAPI."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from gradio.routes import mount_gradio_app

from ...bootstrap import AppContainer
from ...logging_utils import configure_logging
from ..ui.chat_app import create_gradio_blocks
from .dependencies import configure_dependencies, get_settings
from .middleware import IPAllowlistMiddleware
from . import routes


def create_api_app(container: AppContainer) -> FastAPI:
    configure_logging(container.settings.log_path)
    app = FastAPI(title="Samanta RAG", version="0.2.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    configure_dependencies(container.query_handler, container.settings)

    if container.settings.allowed_ips:
        app.add_middleware(IPAllowlistMiddleware, allowed_ips=container.settings.allowed_ips)

    app.include_router(routes.router)

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:  # type: ignore[override]
        return RedirectResponse(url="/chat")

    gradio_app = create_gradio_blocks(container)
    mount_gradio_app(app, gradio_app, path="/chat")

    return app
