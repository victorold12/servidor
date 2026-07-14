"""/api/agent — agente que usa ferramentas (deep agent leve).

O modelo pode chamar `web_search` e `fetch_url` em várias rodadas até resolver a
tarefa. É a base do "deep agent": aqui rodam ferramentas de verdade no servidor,
o que o navegador não faz sozinho. Adicione novas ferramentas em TOOLS + no
despacho abaixo (ex.: ler/escrever arquivo, chamar um conector).
"""
import json

from fastapi import APIRouter, Header
from pydantic import BaseModel

from ..openrouter import chat, content_of, resolve_key
from ..services import scrape_url, web_search

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


async def _run_tool(name: str, args: dict) -> str:
    if name == "web_search":
        return json.dumps(await web_search(args.get("query", ""), 5), ensure_ascii=False)[:4000]
    if name == "fetch_url":
        return json.dumps(await scrape_url(args.get("url", "")), ensure_ascii=False)[:4000]
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

    for _ in range(max(1, body.max_steps)):
        data = await chat(messages, key=key, model=body.model, tools=TOOLS)
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
            output = await _run_tool(fn, args)
            steps.append({"tool": fn, "args": args})
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})

    return {"answer": content_of(data), "steps": steps, "note": "limite de passos atingido"}
