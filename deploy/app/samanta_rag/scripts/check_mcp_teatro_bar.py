#!/usr/bin/env python3
import os
import sys
import ssl
import json
import asyncio
import argparse
from typing import Dict, Any

import aiohttp

try:
    import websockets  # type: ignore
except Exception:  # pragma: no cover
    websockets = None  # type: ignore


def build_payload(tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "call_tool",
        "tool": tool,
        "tool_name": tool,
        "params": args,
        "arguments": args,
        "request_id": os.getenv("REQUEST_ID", "check-mcp")
    }


def build_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


async def check_aiohttp(endpoint: str, token: str, timeout: float, tool: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
    payload = build_payload(tool, tool_args)
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "Samanta-RAG/diag/0.2.0",
    }
    ssl_ctx = build_ssl_context()
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=client_timeout) as session:
        async with session.ws_connect(endpoint, headers=headers, ssl=ssl_ctx, autoping=True) as ws:
            await ws.send_str(json.dumps(payload))
            msg = await ws.receive(timeout=timeout)
            if msg.type == aiohttp.WSMsgType.TEXT:
                raw = msg.data
            elif msg.type == aiohttp.WSMsgType.BINARY:
                raw = msg.data.decode("utf-8", errors="replace")
            else:
                raise RuntimeError(f"Unexpected WS message type: {msg.type}")
    return json.loads(raw)


async def check_websockets(endpoint: str, token: str, timeout: float, tool: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
    if websockets is None:
        raise RuntimeError("websockets no instalado")

    payload = build_payload(tool, tool_args)
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "Samanta-RAG/diag/0.2.0",
    }
    ssl_ctx = build_ssl_context()

    header_list = [(k, v) for k, v in headers.items()]
    try:
        connect_coro = websockets.connect(
            endpoint,
            additional_headers=header_list,
            ssl=ssl_ctx,
        )
    except TypeError:
        connect_coro = websockets.connect(
            endpoint,
            extra_headers=header_list,
            ssl=ssl_ctx,
        )

    async with await asyncio.wait_for(connect_coro, timeout=timeout) as ws:
        await asyncio.wait_for(ws.send(json.dumps(payload)), timeout=timeout)
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    return json.loads(raw)


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
    if not endpoint or not endpoint.startswith("wss://"):
        print("ERROR: MCP_TEATRO_BAR_ENDPOINT vacío o inválido (se espera wss://...)", file=sys.stderr)
        return 2
    if not token:
        print("ERROR: MCP_TOKEN_TEATRO_BAR vacío", file=sys.stderr)
        return 2

    methods = []
    if args.method == "aiohttp":
        methods = ["aiohttp"]
    elif args.method == "websockets":
        methods = ["websockets"]
    else:
        methods = ["aiohttp", "websockets"]

    ok_any = False
    for m in methods:
        try:
            if m == "aiohttp":
                resp = await check_aiohttp(endpoint, token, args.timeout, args.tool, tool_args)
            else:
                resp = await check_websockets(endpoint, token, args.timeout, args.tool, tool_args)
            status = resp.get("status") or resp.get("ok")
            out = {
                "method": m,
                "endpoint": endpoint,
                "ok": bool(status == "ok" or status is True),
                "raw": resp
            }
            print(json.dumps(out, ensure_ascii=False, indent=2 if args.pretty else None))
            ok_any = True
        except Exception as e:
            print(json.dumps({
                "method": m,
                "endpoint": endpoint,
                "ok": False,
                "error": str(e)
            }, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if ok_any else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
