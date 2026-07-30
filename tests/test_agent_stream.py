"""Teste do streaming do /api/agent (contrato de eventos do painel).

Roda sem pytest:  python3 tests/test_agent_stream.py

Sem rede nem LLM real: stub de `chat_stream` e do hub do Agente Local.
Prova que o endpoint com stream=True:
  - emite `token` conforme o modelo responde
  - emite `tool`/`step` quando o modelo usa ferramenta
  - emite `file_begin`/`file_progress` com dados REAIS quando grava arquivo
    no PC (nome e tamanho vêm do que foi pedido, não de template)
  - repassa o progresso que o Agente Local reportar
  - fecha com `usage` e `done`
  - vira `error` honesto quando falta chave ou o agente está offline
  - NÃO emite ferramenta de PC quando não há agent_id (sem Agente Local o
    modelo não ganha esse poder)
  - mantém o contrato antigo (sem stream=True continua devolvendo JSON)
"""
import json
import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

import app.db as db  # noqa: E402

db._DB_PATH = Path(tempfile.mkdtemp()) / "test-stream.db"
os.environ["BACKEND_TOKEN"] = "seg"
import app.config as config  # noqa: E402

config.settings.backend_token = "seg"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.routers import agent as agent_mod  # noqa: E402
from app import pc_tools  # noqa: E402

SESSION = {"X-Backend-Token": "seg", "X-OR-Key": "chave-de-teste"}
_fails = 0


def check(cond, label):
    global _fails
    print(("  ok  " if cond else " FAIL ") + label)
    if not cond:
        _fails += 1


def events(resp):
    """Quebra o NDJSON da resposta em lista de dicionários."""
    out = []
    for line in resp.text.splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def types(evs):
    return [e["type"] for e in evs]


def first(evs, t):
    return next((e for e in evs if e["type"] == t), None)


client = TestClient(app)


# ---------------------------------------------------------------- 1. texto puro
def test_texto_simples():
    print("\n1. resposta de texto: vira tokens + usage + done")

    async def fake_stream(messages, key, model=None, tools=None):
        for pedaco in ["Olá", ", ", "senhor."]:
            yield {"type": "token", "text": pedaco}
        yield {"type": "usage", "total_tokens": 42, "prompt_tokens": 30}
        yield {"type": "finish", "reason": "stop"}

    agent_mod.chat_stream = fake_stream
    r = client.post("/api/agent", headers=SESSION,
                    json={"messages": [{"role": "user", "content": "oi"}], "stream": True})
    evs = events(r)
    check(r.status_code == 200, "responde 200")
    check([e["text"] for e in evs if e["type"] == "token"] == ["Olá", ", ", "senhor."],
          "emite os pedaços de texto na ordem")
    check(first(evs, "usage")["total_tokens"] == 42, "repassa a contagem real de tokens")
    done = first(evs, "done")
    check(done and done["answer"] == "Olá, senhor.", "done traz a resposta completa")
    check(types(evs)[-1] == "done", "done é o último evento")


# ------------------------------------------------------- 2. ferramenta de busca
def test_ferramenta():
    print("\n2. ferramenta: vira tool + step(done)")
    rodadas = []

    async def fake_stream(messages, key, model=None, tools=None):
        rodadas.append(messages)
        if len(rodadas) == 1:
            yield {"type": "tool_calls", "calls": [
                {"id": "c1", "function": {"name": "web_search",
                                          "arguments": '{"query":"eventos"}'}}]}
            yield {"type": "finish", "reason": "tool_calls"}
        else:
            yield {"type": "token", "text": "Achei 3 eventos."}
            yield {"type": "finish", "reason": "stop"}

    async def fake_tool(name, args, routing):
        return json.dumps([{"title": "Evento X"}])

    agent_mod.chat_stream = fake_stream
    agent_mod._run_tool = fake_tool
    r = client.post("/api/agent", headers=SESSION,
                    json={"messages": [{"role": "user", "content": "busca eventos"}],
                          "stream": True})
    evs = events(r)
    tool = first(evs, "tool")
    check(tool and tool["name"] == "web_search", "anuncia a ferramenta usada")
    check(tool and tool["label"] == "Buscando na web", "manda rótulo legível pro painel")
    check(first(evs, "step")["status"] == "done", "fecha a etapa quando termina")
    check(first(evs, "done")["answer"] == "Achei 3 eventos.", "responde depois da ferramenta")
    check(len(rodadas) == 2, "faz a segunda rodada com o resultado da ferramenta")
    check(any(m.get("role") == "tool" for m in rodadas[1]),
          "devolve a observação da ferramenta pro modelo")


# ------------------------------------- 3. arquivo no PC com progresso do agente
def test_arquivo_pc():
    print("\n3. arquivo no PC: file_begin/file_progress com dados reais")

    async def fake_stream(messages, key, model=None, tools=None):
        if not any(m.get("role") == "tool" for m in messages):
            yield {"type": "tool_calls", "calls": [
                {"id": "c1", "function": {
                    "name": "pc_write_file",
                    "arguments": json.dumps({"path": "C:/Users/V/Desktop/Relatorio.txt",
                                             "content": "linha um\nlinha dois"})}}]}
            yield {"type": "finish", "reason": "tool_calls"}
        else:
            yield {"type": "token", "text": "Arquivo gravado."}
            yield {"type": "finish", "reason": "stop"}

    # simula o Agente Local reportando progresso e concluindo
    async def fake_cmd(agent_id, action, args, timeout=300.0):
        check(action == "fs_write", "   traduz pc_write_file -> fs_write")
        check(args["path"].endswith("Relatorio.txt"), "   repassa o caminho pedido")
        yield {"type": "progress", "progress": 40, "status": "Gravando…"}
        yield {"type": "progress", "progress": 80, "status": "Gravando…"}
        yield {"type": "result", "ok": True, "data": "18 bytes gravados",
               "path": "C:/Users/V/Desktop/Relatorio.txt"}

    agent_mod.chat_stream = fake_stream
    pc_tools.run_command_streaming = fake_cmd
    r = client.post("/api/agent", headers=SESSION,
                    json={"messages": [{"role": "user", "content": "grava o relatório"}],
                          "stream": True, "agent_id": "ag-1"})
    evs = events(r)
    fb = first(evs, "file_begin")
    check(fb is not None, "abre o cartão de arquivo")
    check(fb and fb["name"] == "Relatorio", "nome vem do caminho real")
    check(fb and fb["ext"] == "txt", "extensão vem do caminho real")
    check(fb and fb["size"] == len("linha um\nlinha dois".encode()),
          "tamanho é o do conteúdo de verdade")
    progressos = [e["progress"] for e in evs if e["type"] == "file_progress"]
    check(progressos == [40, 80, 100], f"barra segue o agente e fecha em 100 (veio {progressos})")
    fim = [e for e in evs if e["type"] == "file_progress"][-1]
    check(fim["status"] == "Concluído", "status final é Concluído")
    check(fim.get("path", "").endswith("Relatorio.txt"), "informa onde salvou")
    check(first(evs, "done")["files"] == [fb["id"]], "done lista o arquivo gerado")


# ------------------------------------------------- 4. agente offline = erro real
def test_agente_offline():
    print("\n4. Agente Local offline: erro honesto, sem fingir sucesso")

    async def fake_stream(messages, key, model=None, tools=None):
        if not any(m.get("role") == "tool" for m in messages):
            yield {"type": "tool_calls", "calls": [
                {"id": "c1", "function": {"name": "pc_write_file",
                                          "arguments": '{"path":"C:/a.txt","content":"x"}'}}]}
            yield {"type": "finish", "reason": "tool_calls"}
        else:
            yield {"type": "token", "text": "Não consegui gravar."}
            yield {"type": "finish", "reason": "stop"}

    async def fake_cmd(agent_id, action, args, timeout=300.0):
        yield {"type": "error", "message": "Agente Local offline."}

    agent_mod.chat_stream = fake_stream
    pc_tools.run_command_streaming = fake_cmd
    r = client.post("/api/agent", headers=SESSION,
                    json={"messages": [{"role": "user", "content": "grava"}],
                          "stream": True, "agent_id": "ag-1"})
    evs = events(r)
    err = first(evs, "error")
    check(err and "offline" in err["message"], "emite error com o motivo")
    falhou = [e for e in evs if e["type"] == "file_progress" and e["status"] == "Falhou"]
    check(len(falhou) == 1, "marca o cartão do arquivo como falhou")
    check(first(evs, "done") is not None, "ainda fecha o stream (não pendura o painel)")


# ------------------------------- 5. sem agent_id, sem ferramenta de PC ofertada
def test_sem_agente_sem_poder():
    print("\n5. sem Agente Local pareado: modelo não recebe ferramenta de PC")
    vistas = {}

    async def fake_stream(messages, key, model=None, tools=None):
        vistas["nomes"] = [t["function"]["name"] for t in (tools or [])]
        yield {"type": "token", "text": "ok"}
        yield {"type": "finish", "reason": "stop"}

    agent_mod.chat_stream = fake_stream
    client.post("/api/agent", headers=SESSION,
                json={"messages": [{"role": "user", "content": "oi"}], "stream": True})
    check(not any(n.startswith("pc_") for n in vistas["nomes"]),
          f"nenhuma ferramenta pc_* oferecida (veio {vistas['nomes']})")

    client.post("/api/agent", headers=SESSION,
                json={"messages": [{"role": "user", "content": "oi"}],
                      "stream": True, "agent_id": "ag-1"})
    check(any(n.startswith("pc_") for n in vistas["nomes"]),
          "com agent_id as ferramentas de PC aparecem")


# ------------------------------------------------------------ 6. erro sem chave
def test_sem_chave():
    print("\n6. sem chave do OpenRouter: error, não resposta fabricada")

    async def fake_stream(messages, key, model=None, tools=None):
        raise ValueError("Sem chave do OpenRouter (envie no header X-OR-Key).")
        yield  # pragma: no cover

    agent_mod.chat_stream = fake_stream
    r = client.post("/api/agent", headers={"X-Backend-Token": "seg"},
                    json={"messages": [{"role": "user", "content": "oi"}], "stream": True})
    evs = events(r)
    check(first(evs, "error") is not None, "emite error")
    check("chave" in first(evs, "error")["message"].lower(), "explica que falta a chave")
    check(first(evs, "done") is None, "não emite done com resposta vazia")


# --------------------------------------------- 7. contrato antigo não quebrou
def test_contrato_antigo():
    print("\n7. sem stream=True: contrato JSON de antes segue igual")

    async def fake_chat(messages, key, model=None, tools=None, plugins=None):
        return {"choices": [{"message": {"content": "resposta direta"}}]}

    agent_mod.chat = fake_chat
    r = client.post("/api/agent", headers=SESSION,
                    json={"messages": [{"role": "user", "content": "oi"}]})
    check(r.headers["content-type"].startswith("application/json"), "responde JSON")
    check(r.json()["answer"] == "resposta direta", "campo answer intacto")
    check("steps" in r.json(), "campo steps intacto")


for fn in [test_texto_simples, test_ferramenta, test_arquivo_pc, test_agente_offline,
           test_sem_agente_sem_poder, test_sem_chave, test_contrato_antigo]:
    fn()

print("\n" + ("TODOS OS TESTES PASSARAM" if not _fails else f"{_fails} FALHA(S)"))
sys.exit(1 if _fails else 0)
