"""Fila de wake word: o que o PC ouviu esperando o painel buscar.

Sem pytest de propósito (`python3 tests/test_wake_queue.py`), igual aos outros.

O que importa aqui:
  - cada "Ei, JARVIS" é entregue UMA vez (senão o painel repetiria o comando)
  - evento velho não executa quando o painel abre depois
  - a fila não cresce sem limite
  - a rota é protegida por token igual ao resto da gestão de agentes
  - o backend NÃO executa nada por causa de um wake — só enfileira
"""
import os
import sys
import tempfile
import time

os.environ["JARVIS_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "wake.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.routers.agents_hub import _WakeQueue  # noqa: E402

falhas = []


def checa(nome, cond, extra=""):
    if cond:
        print(f"  ok  {nome}")
    else:
        print(f"FALHA {nome} {extra}")
        falhas.append(nome)


print("— fila de wake word")

q = _WakeQueue()
q.push("ag1", {"command": "abre o chrome", "transcript": "ei jarvis abre o chrome",
               "greeted": True, "ts": time.time()})
saida = q.drain("ag1")
checa("entrega o evento", len(saida) == 1 and saida[0]["command"] == "abre o chrome", saida)
checa("drena: segunda chamada vem vazia", q.drain("ag1") == [])

q.push("ag1", {"command": "a", "ts": time.time()})
q.push("ag2", {"command": "b", "ts": time.time()})
checa("fila é por agente", [e["command"] for e in q.drain("ag1")] == ["a"])
checa("o outro agente não foi afetado", [e["command"] for e in q.drain("ag2")] == ["b"])

q.push("ag1", {"command": "velho", "ts": time.time() - (_WakeQueue._TTL + 5)})
q.push("ag1", {"command": "novo", "ts": time.time()})
restou = [e["command"] for e in q.drain("ag1")]
checa("evento velho é descartado", restou == ["novo"], restou)

for i in range(_WakeQueue._MAX + 12):
    q.push("ag3", {"command": f"c{i}", "ts": time.time()})
guardados = q.drain("ag3")
checa("fila não cresce sem limite", len(guardados) == _WakeQueue._MAX, len(guardados))
checa("mantém os mais recentes",
      guardados[-1]["command"] == f"c{_WakeQueue._MAX + 11}", guardados[-1])

checa("agente sem nada devolve lista vazia", q.drain("nunca-existiu") == [])


print("— rota /api/agents/{id}/wake")

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import agents_hub  # noqa: E402

db.init_db()
with db.get_conn() as conn:
    conn.execute(
        "INSERT OR REPLACE INTO paired_agents "
        "(agent_id, name, platform, token_hash, created_at, last_seen_at) "
        "VALUES (?,?,?,?,?,?)",
        ("ag-pc", "PC", "win32", "hash", time.time(), time.time()))

cliente = TestClient(app)

r = cliente.get("/api/agents/ag-pc/wake")
checa("rota responde", r.status_code == 200, r.status_code)
checa("sem eventos, lista vazia", r.json()["events"] == [], r.json())

agents_hub._wake_queue.push("ag-pc", {
    "command": "monta a planilha", "transcript": "ei jarvis monta a planilha",
    "greeted": True, "ts": time.time()})
d = cliente.get("/api/agents/ag-pc/wake").json()
checa("evento chega pela rota", len(d["events"]) == 1 and d["events"][0]["command"] == "monta a planilha", d)
checa("rota também drena", cliente.get("/api/agents/ag-pc/wake").json()["events"] == [])

# o backend é só mensageiro: nada de auditoria nem execução por causa de um wake
with db.get_conn() as conn:
    n = conn.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
checa("wake não gera linha de auditoria nem execução", n == 0, n)

print()
if falhas:
    print(f"{len(falhas)} falha(s): {', '.join(falhas)}")
    sys.exit(1)
print("todos os testes da fila de wake passaram")
