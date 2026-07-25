"""Espelho de conversas + backup automático.

Sem pytest (`python3 tests/test_conversations.py`), igual aos outros.

O que importa aqui é exatamente o que corrompe dados se estiver errado:
  - envio MAIS VELHO não sobrescreve a versão nova (e o painel é avisado)
  - apagar é lápide: conversa apagada não ressuscita quando o outro
    dispositivo reenvia a versão antiga dela
  - mensagem nunca é mesclada — a conversa vencedora vai inteira
  - `since` só traz o que mudou depois (senão sincronizar baixa tudo sempre)
  - o download de snapshot não aceita caminho (`..`), senão vira leitura de
    qualquer arquivo do servidor
  - o snapshot NÃO contém token de pareamento
"""
import gzip
import json
import os
import sys
import tempfile
import time

_TMP = tempfile.mkdtemp()
os.environ["JARVIS_DB_PATH"] = os.path.join(_TMP, "conv.db")
os.environ["BACKUP_DIR"] = os.path.join(_TMP, "backups")
os.environ["BACKUP_KEEP"] = "3"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import autobackup, db  # noqa: E402
from app.main import app  # noqa: E402

falhas = []


def checa(nome, cond, extra=""):
    if cond:
        print(f"  ok  {nome}")
    else:
        print(f"FALHA {nome} {extra}")
        falhas.append(nome)


db.init_db()
cliente = TestClient(app)


def conversa(cid, titulo, ts, msgs):
    return {"id": cid, "title": titulo, "pinned": False, "updated_at": ts,
            "messages": msgs, "extra": {}}


print("— envio e leitura")

t0 = time.time() - 3600      # uma hora atrás: carimbo realista de conversa já escrita
r = cliente.put("/api/conversations", json={"conversations": [
    conversa("c1", "Planilha de eventos", t0, [
        {"role": "user", "content": "monta a planilha"},
        {"role": "assistant", "content": "pronto"}]),
    conversa("c2", "FPS no Valorant", t0 + 1, [{"role": "user", "content": "e o hags?"}]),
]})
checa("envio responde 200", r.status_code == 200, r.status_code)
d = r.json()
checa("as duas foram gravadas", sorted(d["gravadas"]) == ["c1", "c2"], d)
checa("nada recusado", d["recusadas"] == [], d)

d = cliente.get("/api/conversations").json()
checa("leitura devolve as duas", len(d["conversations"]) == 2, d)
c1 = next(c for c in d["conversations"] if c["id"] == "c1")
checa("mensagens voltam iguais", len(c1["messages"]) == 2, c1)
checa("título volta", c1["title"] == "Planilha de eventos", c1)
checa("updated_at volta", abs(c1["updated_at"] - t0) < 0.001, c1)


print("— conflito: última escrita ganha, por conversa")

r = cliente.put("/api/conversations", json={"conversations": [
    conversa("c1", "Editada no celular", t0 + 100, [{"role": "user", "content": "versão nova"}])]}).json()
checa("versão mais nova grava", r["gravadas"] == ["c1"], r)

r = cliente.put("/api/conversations", json={"conversations": [
    conversa("c1", "Editada no PC (velha)", t0 + 50,
             [{"role": "user", "content": "versão velha"}])]}).json()
checa("versão mais velha é RECUSADA", r["gravadas"] == [], r)
checa("e o painel sabe por quê", len(r["recusadas"]) == 1
      and "mais nova" in r["recusadas"][0]["motivo"], r["recusadas"])

c1 = cliente.get("/api/conversations/c1").json()
checa("a vencedora ficou inteira, sem mesclar",
      c1["title"] == "Editada no celular"
      and [m["content"] for m in c1["messages"]] == ["versão nova"], c1)


print("— apagar é lápide, não delete")

r = cliente.delete("/api/conversations/c2").json()
checa("apagar responde ok", r["ok"] and r["existia"], r)
checa("GET da apagada dá 410", cliente.get("/api/conversations/c2").status_code == 410)

d = cliente.get("/api/conversations").json()
checa("não aparece entre as vivas",
      all(c["id"] != "c2" for c in d["conversations"]), d["conversations"])
checa("aparece na lista de apagadas",
      any(x["id"] == "c2" for x in d["deleted"]), d["deleted"])

# o outro dispositivo, que não sincronizou, reenvia a versão antiga
r = cliente.put("/api/conversations", json={"conversations": [
    conversa("c2", "FPS no Valorant", t0 + 1, [{"role": "user", "content": "e o hags?"}])]}).json()
checa("conversa apagada NÃO ressuscita", r["gravadas"] == [], r)
checa("e o motivo é a lápide",
      r["recusadas"] and "apagada" in r["recusadas"][0]["motivo"], r["recusadas"])

# mas uma edição de VERDADE mais nova que a lápide traz de volta (foi escolha
# do usuário mexer nela depois de apagar em outro lugar)
r = cliente.put("/api/conversations", json={"conversations": [
    conversa("c2", "FPS de novo", time.time(), [{"role": "user", "content": "voltei"}])]}).json()
checa("edição mais nova que a lápide restaura", r["gravadas"] == ["c2"], r)


print("— since: só o que mudou")

marca = time.time()
time.sleep(0.01)
cliente.put("/api/conversations", json={"conversations": [
    conversa("c3", "Nova depois da marca", time.time(), [])]})
d = cliente.get(f"/api/conversations?since={marca}").json()
ids = [c["id"] for c in d["conversations"]]
checa("since traz a nova", "c3" in ids, ids)
checa("e não retraz as antigas", "c1" not in ids, ids)

d = cliente.get("/api/conversations?include_payload=false").json()
checa("índice sem payload não traz mensagens",
      all("messages" not in c for c in d["conversations"]), d["conversations"])

print("— relógio adiantado não pode vencer pra sempre")

futuro = time.time() + 86400 * 30      # dispositivo 30 dias adiantado
r = cliente.put("/api/conversations", json={"conversations": [
    conversa("cr", "Relógio doido", futuro, [{"role": "user", "content": "oi"}])]}).json()
checa("grava, mas avisa", r["gravadas"] == ["cr"] and "relogio_ajustado" in r, r)
checa("carimbo foi trazido pra hora do servidor",
      r["relogio_ajustado"][0]["ajustado_para"] <= time.time() + 1, r["relogio_ajustado"])

guardado = cliente.get("/api/conversations/cr").json()
checa("no banco não ficou data futura", guardado["updated_at"] <= time.time() + 1, guardado["updated_at"])

r = cliente.put("/api/conversations", json={"conversations": [
    conversa("cr", "Editada por outro aparelho", time.time(), [{"role": "user", "content": "eu venci"}])]}).json()
checa("outro dispositivo consegue atualizar depois", r["gravadas"] == ["cr"], r)


print("— limites")

grande = "x" * (5 * 1024 * 1024)
r = cliente.put("/api/conversations", json={"conversations": [
    conversa("gigante", "Grande demais", time.time(), [{"role": "user", "content": grande}])]}).json()
checa("conversa acima do teto não é gravada", r["gravadas"] == [], r)
checa("e é dito qual foi", r.get("grandes_demais") == ["gigante"], r)

lote = [conversa(f"L{i}", f"L{i}", time.time(), []) for i in range(250)]
checa("lote maior que o máximo é recusado com 413",
      cliente.put("/api/conversations", json={"conversations": lote}).status_code == 413)

s = cliente.get("/api/conversations/_meta/status").json()
checa("status conta as vivas", s["conversas"] >= 3, s)
checa("status conta as lápides", s["lapides"] >= 0, s)


print("— backup automático")

st = cliente.get("/api/backup/auto").json()
checa("desligado por padrão", st["ligado"] is False, st)
checa("diz onde o snapshot mora", "disco do servidor" in st["onde"], st)
checa("avisa que mesmo disco não protege HD morrendo",
      "HD morrer" in st["aviso"], st["aviso"])

r = cliente.post("/api/backup/auto/run").json()
checa("snapshot manual é escrito", r["ok"] and r["bytes"] > 0, r)
checa("e leva as conversas", r["conversas"] >= 3, r)

bruto = json.loads(gzip.open(r["arquivo"], "rb").read())
checa("snapshot tem memória, conversas e agentes",
      {"memory", "conversations", "agents"} <= set(bruto), list(bruto))
checa("snapshot NÃO tem token de pareamento",
      "token_hash" not in json.dumps(bruto), "token_hash apareceu no snapshot!")

for _ in range(4):
    time.sleep(1.05)          # o nome tem resolução de segundo
    cliente.post("/api/backup/auto/run")
lst = cliente.get("/api/backup/auto/list").json()["snapshots"]
checa("retenção mantém só os N mais recentes", len(lst) == 3, len(lst))

nome = lst[0]["arquivo"]
r = cliente.get(f"/api/backup/auto/download/{nome}")
checa("download do snapshot funciona", r.status_code == 200, r.status_code)
checa("e vem como gzip", r.headers.get("content-type") == "application/gzip",
      r.headers.get("content-type"))

for ruim in ["../../etc/passwd", "..%2f..%2fjarvis.db", "qualquer.txt",
             "jarvis-2026aaaa-111111.json.gz"]:
    code = cliente.get(f"/api/backup/auto/download/{ruim}").status_code
    checa(f"caminho recusado: {ruim} ({code})", code in (400, 404), code)

print()
if falhas:
    print(f"{len(falhas)} falha(s): {', '.join(falhas)}")
    sys.exit(1)
print("todos os testes de conversas e backup automático passaram")
