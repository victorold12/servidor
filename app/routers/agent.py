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
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..openrouter import chat, chat_stream, content_of, resolve_key
from ..router_llm import classify, run_fusion
from ..pc_tools import PC_TOOL_LABEL, PC_TOOLS, run_pc_tool
from ..services import scrape_url, web_search
from .catalog import fetch_catalog
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
    # stream=True devolve NDJSON de eventos (contrato do painel). Sem isso, o
    # endpoint responde JSON de uma vez, como sempre respondeu.
    stream: bool = False
    # Agente Local pareado. Só com ele o modelo ganha as ferramentas de arquivo.
    agent_id: str | None = None
    # Roteamento automático: "auto" | "free" | "fusion". Vazio = usa `model`.
    route: str = ""


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


def _ndjson(event: str, **data) -> str:
    """Uma linha por evento. O painel aceita NDJSON e SSE; NDJSON é mais barato."""
    return json.dumps({"type": event, **data}, ensure_ascii=False) + "\n"


# Rótulo humano por ferramenta — o que o painel mostra na etapa/legenda.
_TOOL_LABEL = {
    "web_search": "Buscando na web",
    "fetch_url": "Lendo a página",
}


def _label_for(tool_name: str) -> str:
    if tool_name in _TOOL_LABEL:
        return _TOOL_LABEL[tool_name]
    if tool_name.startswith("pc_"):
        return PC_TOOL_LABEL.get(tool_name, "Executando no PC")
    if tool_name.startswith("mcp__"):
        return "Ferramenta externa: " + tool_name.rsplit("__", 1)[-1]
    return tool_name


async def _stream_agent(body: AgentIn, key: str):
    """Roda o mesmo laço de ferramentas do `agent`, mas emitindo eventos.

    Contrato dos eventos (o painel depende exatamente destes nomes):
      tool / step        → etapa em execução ou concluída
      file_begin/_progress → arquivo real sendo gerado pelo Agente Local
      token              → pedaço de texto da resposta
      usage              → contagem de tokens/custo reais
      done               → fim, com a resposta completa
      error              → falha honesta (nada de resposta inventada)
    """
    messages = list(body.messages)
    modelo = body.model

    # ---- roteamento automático (RouteLLM), quando pedido ----
    if body.route:
        pedido = next((m.get("content", "") for m in reversed(messages)
                       if m.get("role") == "user"), "")
        try:
            catalogo, _ = await fetch_catalog(key)
        except RuntimeError as exc:
            # sem catálogo não há como rotear; segue no modelo padrão e avisa
            yield _ndjson("route", mode=body.route, fallback=True,
                          note=f"catálogo indisponível ({exc}); usando o modelo padrão")
            catalogo = []

        if catalogo and body.route == "fusion":
            async for ev in run_fusion(messages, catalogo, key):
                if ev["type"] == "answer":
                    yield _ndjson("token", text=ev["text"])
                    yield _ndjson("done", answer=ev["text"], files=[])
                    return
                if ev["type"] == "error":
                    yield _ndjson("error", message=ev["message"])
                    return
                yield _ndjson("route", **{k: v for k, v in ev.items() if k != "type"})
            return

        if catalogo:
            escolhido = await classify(pedido, catalogo, key, body.route == "free")
            if escolhido:
                modelo = escolhido
                yield _ndjson("route", mode=body.route, model=escolhido)
            else:
                yield _ndjson("route", mode=body.route, fallback=True,
                              note="classificador não decidiu; usando o modelo padrão")

    mcp_defs, mcp_routing = await _build_mcp_tools(body.mcp_servers) if body.mcp_servers else ([], {})
    tools = TOOLS + mcp_defs
    # ferramentas de PC só entram se existe um Agente Local pareado pra executar
    if body.agent_id:
        tools = tools + PC_TOOLS

    answer = ""
    usage: dict = {}
    step_index = 0
    files: list[str] = []

    try:
        for _ in range(max(1, body.max_steps)):
            text_parts: list[str] = []
            calls: list[dict] = []

            async for ev in chat_stream(messages, key=key, model=modelo, tools=tools):
                kind = ev.get("type")
                if kind == "token":
                    text_parts.append(ev["text"])
                    answer += ev["text"]
                    yield _ndjson("token", text=ev["text"])
                elif kind == "tool_calls":
                    calls = ev["calls"]
                elif kind == "usage":
                    usage = {k: v for k, v in ev.items() if k != "type"}
                elif kind == "provider":
                    # quem respondeu de verdade (OpenRouter ou modelo local)
                    yield _ndjson("provider", **{k: v for k, v in ev.items() if k != "type"})

            if not calls:
                break

            # o modelo pediu ferramentas: registra a mensagem dele e executa
            messages.append({
                "role": "assistant",
                "content": "".join(text_parts) or None,
                "tool_calls": [
                    {"id": c["id"], "type": "function", "function": c["function"]}
                    for c in calls
                ],
            })

            for call in calls:
                fn = call["function"]["name"]
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}

                yield _ndjson("tool", index=step_index, name=fn, label=_label_for(fn))

                if fn.startswith("pc_") and body.agent_id:
                    # ação de PC: o Agente Local executa e vai reportando progresso
                    output = ""
                    async for pev in run_pc_tool(body.agent_id, fn, args):
                        etype = pev.get("type")
                        if etype == "file_begin":
                            files.append(pev["id"])
                            yield _ndjson("file_begin", **{k: v for k, v in pev.items() if k != "type"})
                        elif etype == "file_progress":
                            yield _ndjson("file_progress", **{k: v for k, v in pev.items() if k != "type"})
                        elif etype == "error":
                            yield _ndjson("error", message=pev["message"])
                            output = f"ERRO: {pev['message']}"
                        elif etype == "output":
                            output = pev["text"]
                else:
                    output = await _run_tool(fn, args, mcp_routing)

                yield _ndjson("step", index=step_index, status="done")
                step_index += 1
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})

        if usage:
            yield _ndjson("usage", **usage)
        yield _ndjson("done", answer=answer, files=files)

    except ValueError as exc:            # sem chave do OpenRouter
        yield _ndjson("error", message=str(exc))
    except Exception as exc:             # noqa: BLE001 — o painel precisa saber o que falhou
        yield _ndjson("error", message=f"Falha no agente: {exc}")


@router.post("/agent")
async def agent(
    body: AgentIn,
    x_or_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    key = resolve_key(x_or_key or authorization)

    if body.stream:
        return StreamingResponse(
            _stream_agent(body, key),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

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
