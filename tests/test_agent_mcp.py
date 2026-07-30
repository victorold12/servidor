"""Teste do MCP nativo no deep-agent (routers/agent.py).

Roda sem pytest:  python3 tests/test_agent_mcp.py

Sem rede nem LLM real: stub de `chat` e dos helpers MCP (mcp_list_tools/
mcp_call_tool). Prova que o agente:
  - lista as ferramentas do servidor MCP e as embrulha como function tools
  - quando o modelo chama uma tool MCP, despacha pro servidor MCP certo
  - devolve a resposta final do modelo
"""
import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

import app.db as db  # noqa: E402

db._DB_PATH = Path(tempfile.mkdtemp()) / "test-agent.db"
os.environ["BACKEND_TOKEN"] = "seg"
import app.config as config  # noqa: E402

config.settings.backend_token = "seg"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.routers import agent as agent_mod  # noqa: E402

SESSION = {"X-Backend-Token": "seg"}
_fails = 0
_mcp_calls = []


def check(cond, label):
    global _fails
    print(("  ok  " if cond else " FAIL ") + label)
    if not cond:
        _fails += 1


async def fake_list_tools(server_url, headers=None):
    return {"tools": [{
        "name": "soma",
        "description": "Soma dois números",
        "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}},
    }]}


async def fake_call_tool(server_url, tool, arguments, headers=None):
    _mcp_calls.append((server_url, tool, arguments))
    return {"content": [{"type": "text", "text": "resultado 7"}]}


_chat_calls = {"n": 0}


async def fake_chat(messages, key=None, model=None, tools=None):
    _chat_calls["n"] += 1
    if _chat_calls["n"] == 1:
        # 1ª rodada: o modelo decide chamar a ferramenta MCP embrulhada
        # confirma que a tool MCP foi oferecida ao modelo
        names = [t["function"]["name"] for t in (tools or [])]
        assert any(n.startswith("mcp__0__") for n in names), f"tool MCP não oferecida: {names}"
        return {"choices": [{"message": {
            "role": "assistant", "content": "",
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "mcp__0__soma", "arguments": '{"a":3,"b":4}'}}],
        }}]}
    # 2ª rodada: entrega a resposta final
    return {"choices": [{"message": {"role": "assistant", "content": "A soma é 7."}}]}


def main():
    agent_mod.mcp_list_tools = fake_list_tools
    agent_mod.mcp_call_tool = fake_call_tool
    agent_mod.chat = fake_chat

    with TestClient(app) as client:
        r = client.post("/api/agent", headers=SESSION, json={
            "messages": [{"role": "user", "content": "quanto é 3+4?"}],
            "mcp_servers": ["http://fake-mcp.local/mcp"],
            "max_steps": 4,
        })
        check(r.status_code == 200, "endpoint respondeu 200")
        body = r.json()
        check(body.get("answer") == "A soma é 7.", f"resposta final do modelo: {body.get('answer')!r}")
        check(len(_mcp_calls) == 1, "a ferramenta MCP foi despachada uma vez")
        check(_mcp_calls and _mcp_calls[0][1] == "soma", "despachou pro nome REAL da tool (soma), não o embrulhado")
        check(_mcp_calls and _mcp_calls[0][2] == {"a": 3, "b": 4}, "passou os argumentos certos pro servidor MCP")
        check(any(s["tool"] == "mcp__0__soma" for s in body.get("steps", [])), "passo registrado com o nome embrulhado")

    if _fails:
        print(f"\n{_fails} CHECK(S) FALHARAM ✗")
        sys.exit(1)
    print("\nTODOS OS CHECKS PASSARAM ✓")


if __name__ == "__main__":
    main()
