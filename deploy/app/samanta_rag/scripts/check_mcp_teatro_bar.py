#!/usr/bin/env python3
import argparse
import asyncio
import json
import os
import ssl
import sys
import uuid
from dataclasses import dataclass
from typing import Any, Dict

import aiohttp

try:  # pragma: no cover - opcional según entorno
    import websockets  # type: ignore
except Exception:  # pragma: no cover
    websockets = None  # type: ignore


JSONRPC_VERSION = "2.0"
USER_AGENT = "Samanta-RAG/diag/0.3.0"


def build_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def _jsonrpc(message_id: str, method: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "id": message_id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


@dataclass(slots=True)
class MCPDiagClient:
    endpoint: str
    token: str
    timeout: float

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "User-Agent": USER_AGENT,
        }

    async def call_via_aiohttp(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ssl_ctx = None if self.endpoint.startswith("ws://") else build_ssl_context()
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        subprotocols = ("mcp.events.v1", "mcp")

        async with aiohttp.ClientSession(timeout=timeout, headers=self._headers()) as session:
            async with session.ws_connect(
                self.endpoint,
                ssl=ssl_ctx,
                autoping=True,
                protocols=subprotocols,
            ) as ws:
                await ws.send_str(json.dumps(payload))
                response = await ws.receive(timeout=self.timeout)
                if response.type == aiohttp.WSMsgType.TEXT:
                    raw = response.data
                elif response.type == aiohttp.WSMsgType.BINARY:
                    raw = response.data.decode("utf-8", errors="replace")
                else:
                    raise RuntimeError(f"Unexpected WS message type: {response.type}")
        return json.loads(raw)

    async def call_via_websockets(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if websockets is None:
            raise RuntimeError("websockets no instalado")

        ssl_ctx = None if self.endpoint.startswith("ws://") else build_ssl_context()
        header_list = list(self._headers().items())
        subprotocols = ("mcp.events.v1", "mcp")

        connect_coro = websockets.connect(
            self.endpoint,
            extra_headers=header_list,
            ssl=ssl_ctx,
            subprotocols=list(subprotocols),
        )

        ws = await asyncio.wait_for(connect_coro, timeout=self.timeout)
        try:
            await asyncio.wait_for(ws.send(json.dumps(payload)), timeout=self.timeout)
            raw = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
        finally:
            try:
                await asyncio.wait_for(ws.close(), timeout=self.timeout)
            except Exception:
                pass
        return json.loads(raw)


async def run_diagnostic(client: MCPDiagClient, tool: str, tool_args: Dict[str, Any], method: str) -> Dict[str, Any]:
    init_id = str(uuid.uuid4())
    call_id = str(uuid.uuid4())
    payloads = [
        _jsonrpc(init_id, "initialize", {"protocol_versions": ["mcp/1.0"]}),
        _jsonrpc(
            call_id,
            "call_tool",
            {
                "name": tool,
                "arguments": {
                    **tool_args,
                    "token": client.token,
                    "token_internal": client.token,
                },
            },
        ),
    ]

    responses: list[Dict[str, Any]] = []
    for body in payloads:
        if method == "aiohttp":
            responses.append(await client.call_via_aiohttp(body))
        else:
            responses.append(await client.call_via_websockets(body))
    return {"responses": responses}


async def main() -> int:
    parser = argparse.ArgumentParser(description="Chequeo WSS MCP teatro-bar (call_tool)")
    parser.add_argument("--method", choices=["auto", "aiohttp", "websockets"], default="auto")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--tool", type=str, default="health.ping", help="Nombre de tool, ej: events.this_week")
    parser.add_argument("--params-json", type=str, default="{}", help="JSON con argumentos para la tool")
    parser.add_argument("--pretty", action="store_true", help="Imprimir salida formateada")
    args = parser.parse_args()

    try:
        tool_args: Dict[str, Any] = json.loads(args.params_json)
        if not isinstance(tool_args, dict):
            raise ValueError("params-json debe ser un objeto JSON")
    except Exception as e:
        print(f"ERROR: params-json inválido: {e}", file=sys.stderr)
        return 2

    endpoint = os.getenv("MCP_TEATRO_BAR_ENDPOINT", "").strip()
    token = os.getenv("MCP_TOKEN_TEATRO_BAR", "").strip()
    if not endpoint or not (endpoint.startswith("wss://") or endpoint.startswith("ws://")):
        print("ERROR: MCP_TEATRO_BAR_ENDPOINT vacío o inválido (se espera wss://... o ws:// para debug)", file=sys.stderr)
        return 2
    if not token:
        print("ERROR: MCP_TOKEN_TEATRO_BAR vacío", file=sys.stderr)
        return 2

    methods = [args.method] if args.method in {"aiohttp", "websockets"} else ["aiohttp", "websockets"]
    client = MCPDiagClient(endpoint=endpoint, token=token, timeout=args.timeout)

    ok_any = False
    for m in methods:
        try:
            report = await run_diagnostic(client, args.tool, tool_args, m)
            print(json.dumps({"method": m, "endpoint": endpoint, "ok": True, "raw": report}, ensure_ascii=False, indent=2 if args.pretty else None))
            ok_any = True
        except Exception as e:
            print(json.dumps({"method": m, "endpoint": endpoint, "ok": False, "error": str(e)}, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if ok_any else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
