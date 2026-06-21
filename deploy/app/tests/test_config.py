"""Tests de carga de configuración multi-tenant."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from samanta_rag.config import TenantConfig, load_tenants, settings


def _write_tenant(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_load_tenants_fallback_when_directory_missing() -> None:
    """Sin TENANTS_PATH, load_tenants debe devolver un único tenant default."""
    with TemporaryDirectory() as tmp:
        os.environ["TENANTS_PATH"] = str(Path(tmp) / "no_existe")
        try:
            tenants, default_id = load_tenants(settings)
            assert default_id == "default"
            assert list(tenants.keys()) == ["default"]
            assert tenants["default"].mcp_from_env is True
            assert tenants["default"].documents_path == settings.documents_path
        finally:
            del os.environ["TENANTS_PATH"]


def test_load_tenants_from_json_files() -> None:
    """Debe cargar todos los JSONs válidos del directorio."""
    with TemporaryDirectory() as tmp:
        tenants_dir = Path(tmp)
        os.environ["TENANTS_PATH"] = str(tenants_dir)
        _write_tenant(
            tenants_dir / "teatro.json",
            {
                "id": "teatro",
                "system_prompt": "T",
                "documents_path": "/data/markdown/teatro",
                "vectorstore_path": "/data/vectorstore/teatro",
                "llm_provider": "openai",
                "model_name": "gpt-4o-mini",
                "enabled": True,
            },
        )
        _write_tenant(
            tenants_dir / "portfolio.json",
            {
                "id": "portfolio",
                "system_prompt": "P",
                "documents_path": "/data/markdown/portfolio",
                "vectorstore_path": "/data/vectorstore/portfolio",
                "enabled": True,
            },
        )
        try:
            os.environ.pop("DEFAULT_TENANT", None)
            tenants, default_id = load_tenants(settings)
            assert sorted(tenants.keys()) == ["portfolio", "teatro"]
            assert default_id == "portfolio"  # fallback al primero por orden alfabético
            teatro = tenants["teatro"]
            assert teatro.llm_provider == "openai"
            assert teatro.model_name == "gpt-4o-mini"
            assert teatro.mcp_from_env is False
            portfolio = tenants["portfolio"]
            assert portfolio.llm_provider == settings.llm_provider
        finally:
            del os.environ["TENANTS_PATH"]


def test_load_tenants_respects_default_tenant_env() -> None:
    """DEFAULT_TENANT debe forzar el tenant por defecto si existe."""
    with TemporaryDirectory() as tmp:
        tenants_dir = Path(tmp)
        os.environ["TENANTS_PATH"] = str(tenants_dir)
        os.environ["DEFAULT_TENANT"] = "teatro"
        _write_tenant(
            tenants_dir / "teatro.json",
            {
                "id": "teatro",
                "system_prompt": "T",
                "documents_path": "/data/markdown/teatro",
                "vectorstore_path": "/data/vectorstore/teatro",
                "enabled": True,
            },
        )
        _write_tenant(
            tenants_dir / "portfolio.json",
            {
                "id": "portfolio",
                "system_prompt": "P",
                "documents_path": "/data/markdown/portfolio",
                "vectorstore_path": "/data/vectorstore/portfolio",
                "enabled": True,
            },
        )
        try:
            tenants, default_id = load_tenants(settings)
            assert default_id == "teatro"
        finally:
            del os.environ["TENANTS_PATH"]
            del os.environ["DEFAULT_TENANT"]


def test_load_tenants_ignores_invalid_json() -> None:
    """JSONs inválidos se ignoran y se loguean."""
    with TemporaryDirectory() as tmp:
        tenants_dir = Path(tmp)
        os.environ["TENANTS_PATH"] = str(tenants_dir)
        _write_tenant(
            tenants_dir / "ok.json",
            {
                "id": "ok",
                "system_prompt": "OK",
                "documents_path": "/data/markdown/ok",
                "vectorstore_path": "/data/vectorstore/ok",
                "enabled": True,
            },
        )
        (tenants_dir / "bad.json").write_text("not json", encoding="utf-8")
        try:
            tenants, default_id = load_tenants(settings)
            assert list(tenants.keys()) == ["ok"]
            assert default_id == "ok"
        finally:
            del os.environ["TENANTS_PATH"]


def test_tenant_config_is_immutable() -> None:
    """TenantConfig debe ser frozen."""
    tenant = TenantConfig(
        id="x",
        system_prompt="s",
        documents_path=Path("/d"),
        vectorstore_path=Path("/v"),
    )
    try:
        tenant.id = "y"  # type: ignore[misc]
    except AttributeError:
        pass
    else:
        raise AssertionError("TenantConfig no es inmutable")


def test_load_tenants_resolves_relative_paths_from_json_location() -> None:
    """Los paths relativos en el JSON se resuelven desde el directorio del JSON."""
    with TemporaryDirectory() as tmp:
        tenants_dir = Path(tmp) / "tenants"
        tenants_dir.mkdir()
        data_dir = Path(tmp) / "data"
        markdown_dir = data_dir / "markdown" / "x"
        vectorstore_dir = data_dir / "vectorstore" / "x"
        markdown_dir.mkdir(parents=True)
        vectorstore_dir.mkdir(parents=True)
        os.environ["TENANTS_PATH"] = str(tenants_dir)
        _write_tenant(
            tenants_dir / "x.json",
            {
                "id": "x",
                "system_prompt": "S",
                "documents_path": "../data/markdown/x",
                "vectorstore_path": "../data/vectorstore/x",
                "enabled": True,
            },
        )
        try:
            tenants, _ = load_tenants(settings)
            x = tenants["x"]
            assert x.documents_path == markdown_dir
            assert x.vectorstore_path == vectorstore_dir
        finally:
            del os.environ["TENANTS_PATH"]


def test_load_tenants_keeps_absolute_paths() -> None:
    """Los paths absolutos en el JSON se conservan sin modificación."""
    with TemporaryDirectory() as tmp:
        tenants_dir = Path(tmp)
        os.environ["TENANTS_PATH"] = str(tenants_dir)
        _write_tenant(
            tenants_dir / "abs.json",
            {
                "id": "abs",
                "system_prompt": "S",
                "documents_path": "/tmp/abs/docs",
                "vectorstore_path": "/tmp/abs/vectors",
                "enabled": True,
            },
        )
        try:
            tenants, _ = load_tenants(settings)
            abs_cfg = tenants["abs"]
            assert abs_cfg.documents_path == Path("/tmp/abs/docs")
            assert abs_cfg.vectorstore_path == Path("/tmp/abs/vectors")
        finally:
            del os.environ["TENANTS_PATH"]
