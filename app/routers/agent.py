"""/api/agent — agente que usa ferramentas (deep agent leve).

O modelo pode chamar `web_search` e `fetch_url` em várias rodadas até resolver a
tarefa. É a base do "deep agent": aqui rodam ferramentas de verdade no servidor,
o que o navegador não faz sozinho.

MCP nativo (Seção 13.1): além das ferramentas locais, o agente pode consumir as
ferramentas de servidores MCP externos como se fossem nativas — passe
`mcp_servers` no corpo. Cada ferramenta MCP vira uma function tool com nome
`mcp__<i>__<tool>`, e a chamada é despachada pro servidor MCP via mcp_client.
O protocolo que o LLM fala continua sendo tool-calling (é o que os modelos do
OpenRouter entendem); MCP é a camada agente↔servidor-de-ferramentas, que é
exatamente pra isso que o MCP existe.
"""
import json
import re

from fastapi import APIRouter, Header
from pydantic import BaseModel

from ..openrouter import chat, content_of, resolve_key
from ..services import scrape_url, web_search
from .mcp_client import mcp_call_tool, mcp_list_tools

router = APIRouter()

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Busca na web e retorna títulos, links e trechos.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Baixa uma URL e extrai título, descrição, imagem e texto.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
]


class AgentIn(BaseModel):
    messages: list[dict]
    model: str | None = None
    max_steps: int = 6
    # URLs de servidores MCP (Streamable HTTP) cujas ferramentas o agente pode usar.
    mcp_servers: list[str] = []


def _sanitize_tool_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", str(name))[:48] or "tool"


async def _build_mcp_tools(servers: list[str]) -> tuple[list[dict], dict]:
    """Lista as ferramentas de cada servidor MCP e as embrulha como function
    tools do agente. Devolve (defs, routing) onde routing[nome_embrulhado] =
    (server_url, nome_real). Um servidor inacessível é ignorado (best-effort) —
    não derruba o agente."""
    defs: list[dict] = []
    routing: dict[str, tuple[str, str]] = {}
    for idx, server in enumerate(servers):
        try:
            listing = await mcp_list_tools(server)
        except Exception:  # noqa: BLE001 — servidor MCP fora do ar não quebra o agente
            continue
        for tool in (listing or {}).get("tools", []):
            real = tool.get("name")
            if not real:
                continue
            wrapped = f"mcp__{idx}__{_sanitize_tool_name(real)}"
            defs.append({
                "type": "function",
                "function": {
                    "name": wrapped,
                    "description": (tool.get("description") or f"Ferramenta MCP {real}")[:300],
                    "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
                },
            })
            routing[wrapped] = (server, real)
    return defs, routing


async def _run_tool(name: str, args: dict, mcp_routing: dict) -> str:
    if name == "web_search":
        return json.dumps(await web_search(args.get("query", ""), 5), ensure_ascii=False)[:4000]
    if name == "fetch_url":
        return json.dumps(await scrape_url(args.get("url", "")), ensure_ascii=False)[:4000]
    if name in mcp_routing:
        server, real = mcp_routing[name]
        try:
            result = await mcp_call_tool(server, real, args)
            return json.dumps(result, ensure_ascii=False)[:4000]
        except Exception as exc:  # noqa: BLE001 — erro vira observação, o modelo decide
            return f"ERRO na ferramenta MCP {real}: {exc}"
    return f"ferramenta desconhecida: {name}"


@router.post("/agent")
async def agent(
    body: AgentIn,
    x_or_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    key = resolve_key(x_or_key or authorization)
    messages = list(body.messages)
    steps: list[dict] = []
    data: dict = {}

    mcp_defs, mcp_routing = await _build_mcp_tools(body.mcp_servers) if body.mcp_servers else ([], {})
    tools = TOOLS + mcp_defs

    for _ in range(max(1, body.max_steps)):
        data = await chat(messages, key=key, model=body.model, tools=tools)
        message = data["choices"][0]["message"]
        messages.append(message)
        calls = message.get("tool_calls")
        if not calls:
            return {"answer": message.get("content", ""), "steps": steps}
        for call in calls:
            fn = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            output = await _run_tool(fn, args, mcp_routing)
            steps.append({"tool": fn, "args": args})
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})

    return {"answer": content_of(data), "steps": steps, "note": "limite de passos atingido"}
