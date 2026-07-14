"""/api/mcp/* — cliente MCP mínimo (Streamable HTTP), sem SDK.

Conecta a um servidor MCP que fale o transporte HTTP (Streamable HTTP), lista as
ferramentas e chama uma. Feito com httpx puro pra não brigar com as dependências
do FastAPI (o SDK oficial exige uma versão de starlette incompatível).

Honesto: isto é um cliente BEST-EFFORT e não foi testado contra um servidor MCP
real neste ambiente. Cobre initialize -> tools/list -> tools/call sobre HTTP.
Servidores MCP só-stdio (locais) não se encaixam aqui — esses são o caminho do
app instalado (pywebview), não de um backend remoto.
"""
import json

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import settings

router = APIRouter()

PROTOCOL_VERSION = "2025-06-18"


class ToolsIn(BaseModel):
    server_url: str
    headers: dict | None = None


class CallIn(BaseModel):
    server_url: str
    tool: str
    arguments: dict = {}
    headers: dict | None = None


def _parse(resp: httpx.Response) -> dict:
    """Aceita resposta JSON simples ou stream SSE (data: {...})."""
    if "text/event-stream" in resp.headers.get("content-type", ""):
        found = None
        for line in resp.text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                try:
                    obj = json.loads(line[5:].strip())
                    if "result" in obj or "error" in obj:
                        found = obj
                except json.JSONDecodeError:
                    continue
        if found is None:
            raise HTTPException(status_code=502, detail="SSE do MCP sem JSON-RPC válido")
        return found
    return resp.json()


async def _rpc(server_url: str, extra_headers: dict | None, method: str, params: dict, rid: int):
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if extra_headers:
        headers.update(extra_headers)
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        # 1) initialize
        init = await client.post(server_url, headers=headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "VTz LLM Backend", "version": "0.1.0"},
            },
        })
        if init.status_code >= 400:
            raise HTTPException(status_code=init.status_code, detail=init.text[:500])
        session_id = init.headers.get("mcp-session-id")
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        # 2) notifications/initialized
        await client.post(server_url, headers=headers,
                          json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        # 3) a chamada de fato
        resp = await client.post(server_url, headers=headers,
                                 json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])
        obj = _parse(resp)
        if "error" in obj:
            raise HTTPException(status_code=502, detail=json.dumps(obj["error"]))
        return obj.get("result")


@router.post("/tools")
async def mcp_tools(body: ToolsIn):
    """Lista as ferramentas expostas por um servidor MCP."""
    return await _rpc(body.server_url, body.headers, "tools/list", {}, 2)


@router.post("/call")
async def mcp_call(body: CallIn):
    """Chama uma ferramenta de um servidor MCP."""
    return await _rpc(body.server_url, body.headers, "tools/call",
                      {"name": body.tool, "arguments": body.arguments}, 3)
