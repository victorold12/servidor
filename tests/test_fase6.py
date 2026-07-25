"""Teste de analytics, backup/import, fallback Ollama e webhook Discord/Telegram.

Roda sem pytest:  python3 tests/test_fase6.py

Sem rede: stub do cliente HTTP.

O foco é onde essas features podem machucar:
  - analytics em cima de log adulterado tem que AVISAR, não exibir número bonito
  - export NÃO pode levar token de agente (backup vazado ≠ acesso ao PC)
  - import não é destrutivo por padrão; replace precisa ser pedido
  - import descarta aresta órfã e não restaura agente pareado nem auditoria
  - fallback Ollama: usa o local sem chave, avisa quem respondeu, e sem
    fallback configurado falha de forma honesta
  - webhook: sem segredo fica desligado; segredo errado é 404; sem allowlist
    recusa tudo; quem não está na lista é ignorado
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

import app.db as db  # noqa: E402

db._DB_PATH = Path(tempfile.mkdtemp()) / "test-fase6.db"
os.environ["BACKEND_TOKEN"] = "seg"
import app.config as config  # noqa: E402

config.settings.backend_token = "seg"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app import openrouter as orm  # noqa: E402
from app import security as sec_mod  # noqa: E402
from app.routers import messaging as msg_mod  # noqa: E402

db.init_db()

SESSION = {"X-Backend-Token": "seg"}
_fails = 0


def check(cond, label):
    global _fails
    print(("  ok  " if cond else " FAIL ") + label)
    if not cond:
        _fails += 1


def zera():
    sec_mod._hits.clear()


client = TestClient(app)


# ============================================================ ANALYTICS
def semeia_auditoria():
    """Grava auditoria pela função real, pra a cadeia de hash ficar válida."""
    from app.routers.agents_hub import _write_audit
    agora = time.time()
    with db.get_conn() as conn:
        conn.execute("DELETE FROM audit_log")
    for i, (acao, tier, dec) in enumerate([
        ("fs_write", 1, "auto"), ("fs_write", 1, "auto"), ("fs_read", 1, "auto"),
        ("fs_delete", 3, "deny"), ("run", 2, "confirmed"),
    ]):
        _write_audit("ag-1", {
            "action_type": acao, "target": f"C:/x/arquivo{i}.txt", "tier": tier,
            "decision": dec, "result": "ok", "ts": agora - i * 60,
        })


def test_analytics():
    print("\n1. analytics agrega o log que a auditoria já grava")
    zera()
    semeia_auditoria()
    j = client.get("/api/analytics?days=7", headers=SESSION).json()
    check(j["total"] == 5, f"conta as 5 ações (veio {j['total']})")
    check(j["days"] == 7 and j["from_ts"] > 0, "declara a janela (senão o número não diz nada)")
    top = j["acoes"][0]
    check(top["tipo"] == "fs_write" and top["total"] == 2, "ranking por ação")
    check(top["label"] == "Gravar arquivo", "traduz o nome técnico")
    check(j["negadas"] == 1, "conta as negadas")
    check(any(t["tier"] == 3 and t["label"] == "fora do padrão" for t in j["tiers"]),
          "quebra por tier com rótulo")
    check(j["chain_ok"] is True, "cadeia de hash fecha")
    check("chain_warning" not in j, "sem aviso quando está tudo íntegro")


def test_analytics_log_adulterado():
    print("\n2. log adulterado: analytics AVISA em vez de exibir número bonito")
    zera()
    semeia_auditoria()
    with db.get_conn() as conn:
        conn.execute("UPDATE audit_log SET target = 'mexido' WHERE id = (SELECT MIN(id) FROM audit_log)")
    j = client.get("/api/analytics", headers=SESSION).json()
    check(j["chain_ok"] is False, "detecta que a cadeia quebrou")
    check("não confiáveis" in j.get("chain_warning", ""), "diz que os números não são confiáveis")


def test_analytics_vazio():
    print("\n3. janela sem ação: diz que está vazia")
    zera()
    with db.get_conn() as conn:
        conn.execute("DELETE FROM audit_log")
    j = client.get("/api/analytics?days=1", headers=SESSION).json()
    check(j["total"] == 0 and "nenhuma ação" in j.get("note", ""), "explica o vazio")


# ============================================================== BACKUP
def semeia_memoria():
    with db.get_conn() as conn:
        for t in ("memory_nodes", "memory_edges", "memory_daily", "memory_vectors"):
            conn.execute(f"DELETE FROM {t}")
        conn.executemany(
            "INSERT INTO memory_nodes (user_id, node_id, label, type, created_at) VALUES (?,?,?,?,?)",
            [("victor", "victor", "Victor", "pessoa", time.time()),
             ("victor", "belem", "Belém", "lugar", time.time())])
        conn.execute(
            "INSERT INTO memory_edges (user_id, source, relation, target, confidence) "
            "VALUES ('victor','victor','mora em','belem',0.9)")
        conn.execute(
            "INSERT INTO memory_daily (user_id, day, summary, fact_count, updated_at) "
            "VALUES ('victor','2026-07-25','Resumo.',2,?)", (time.time(),))


def test_export_sem_token_de_agente():
    print("\n4. export não leva token de agente (backup vazado ≠ acesso ao PC)")
    zera()
    semeia_memoria()
    with db.get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO paired_agents "
            "(agent_id, name, platform, token_hash, created_at) VALUES (?,?,?,?,?)",
            ("ag-1", "PC do Victor", "win32", "SEGREDO123", time.time()))

    j = client.get("/api/backup/export", headers=SESSION).json()
    bruto = json.dumps(j)
    check(j["format"] == "vtz-backup/1", "declara o formato")
    check("SEGREDO123" not in bruto, "o token do agente NÃO está no pacote")
    check(all("token_hash" not in a for a in j["agents"]), "nem o campo aparece")
    check(any(a["agent_id"] == "ag-1" for a in j["agents"]), "mas o agente é listado")
    check(len(j["memory"]["nodes"]) == 2 and len(j["memory"]["edges"]) == 1,
          "memória vai completa")
    check(len(j["memory"]["daily"]) == 1, "camada diária vai também")
    check("audit_chain_ok" in j, "informa se a auditoria exportada estava íntegra")


def test_import_merge_e_replace():
    print("\n5. import: merge é o padrão; replace precisa ser pedido")
    zera()
    semeia_memoria()
    pacote = {
        "format": "vtz-backup/1",
        "memory": {
            "nodes": [{"node_id": "sao-paulo", "label": "São Paulo", "type": "lugar"}],
            "edges": [{"source": "victor", "relation": "visitou", "target": "sao-paulo"}],
            "daily": [],
        },
    }
    j = client.post("/api/backup/import", headers=SESSION, json=pacote).json()
    check(j["mode"] == "merge", "modo padrão é merge")
    check(j["totais_agora"]["nodes"] == 3, f"acrescentou sem apagar (veio {j['totais_agora']['nodes']})")

    j2 = client.post("/api/backup/import", headers=SESSION,
                     json=dict(pacote, mode="replace")).json()
    check(j2["totais_agora"]["nodes"] == 1, "replace troca tudo pelo pacote")
    check("reindex" in j2.get("note", ""), "avisa que os vetores precisam ser recalculados")


def test_import_valida():
    print("\n6. import descarta lixo em vez de gravar grafo quebrado")
    zera()
    semeia_memoria()
    j = client.post("/api/backup/import", headers=SESSION, json={
        "format": "vtz-backup/1", "mode": "replace",
        "memory": {
            "nodes": [{"node_id": "ok", "label": "Válido"}, {"label": "sem id"}, "texto solto"],
            "edges": [{"source": "ok", "relation": "x", "target": "nao-existe"},
                      {"source": "ok", "relation": "y", "target": "ok"}],
        }}).json()
    check(j["importados"]["nodes"] == 1, "só o nó válido entra")
    check(j["descartados"]["nodes"] == 2, "reporta os descartados")
    check(j["importados"]["edges"] == 1, "aresta órfã fica fora")
    check(j["descartados"]["edges"] == 1, "e é reportada")

    ruim = client.post("/api/backup/import", headers=SESSION,
                       json={"format": "outro/9", "memory": {}})
    check(ruim.status_code == 400, "formato desconhecido é recusado")


def test_import_nao_restaura_pareamento():
    print("\n7. import não recria agente pareado nem auditoria")
    zera()
    with db.get_conn() as conn:
        antes_ag = conn.execute("SELECT COUNT(*) c FROM paired_agents").fetchone()["c"]
    client.post("/api/backup/import", headers=SESSION, json={
        "format": "vtz-backup/1",
        "memory": {"nodes": [], "edges": []},
        "agents": [{"agent_id": "invasor", "name": "PC do atacante"}],
        "audit": [{"agent_id": "invasor", "ts": 1, "action_type": "run",
                   "target": "x", "tier": 1, "decision": "auto", "result": "ok"}],
    }).json()
    with db.get_conn() as conn:
        depois_ag = conn.execute("SELECT COUNT(*) c FROM paired_agents").fetchone()["c"]
        invasor = conn.execute(
            "SELECT COUNT(*) c FROM audit_log WHERE agent_id = 'invasor'").fetchone()["c"]
    check(depois_ag == antes_ag, "nenhum agente novo foi pareado por arquivo")
    check(invasor == 0, "nenhuma linha de auditoria injetada")


# ======================================================== OLLAMA FALLBACK
class FakeResp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._p


def fake_http(comportamento):
    """comportamento(url) -> FakeResp, ou levanta."""
    class C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            return comportamento(url, json)
    orm.httpx.AsyncClient = C


def test_ollama_sem_chave():
    print("\n8. sem chave: usa o Ollama local e diz que foi ele")
    import asyncio
    config.settings.ollama_base = "http://localhost:11434/v1"
    config.settings.ollama_model = "llama3.2"
    vistos = {}

    def comp(url, corpo):
        vistos["url"] = url
        vistos["model"] = corpo["model"]
        return FakeResp({"choices": [{"message": {"content": "resposta local"}}]})
    fake_http(comp)

    data = asyncio.get_event_loop().run_until_complete(
        orm.chat([{"role": "user", "content": "oi"}], key=""))
    check(data["_provider"] == "ollama", "marca o provedor como ollama")
    check("11434" in vistos["url"], "chamou o endpoint local")
    check(vistos["model"] == "llama3.2", "usou o modelo local configurado")
    check(orm.content_of(data) == "resposta local", "resposta chega normal")


def test_ollama_quando_openrouter_cai():
    print("\n9. OpenRouter fora do ar: cai no local")
    import asyncio
    chamadas = []

    def comp(url, corpo):
        chamadas.append(url)
        if "openrouter" in url:
            raise RuntimeError("sem internet")
        return FakeResp({"choices": [{"message": {"content": "local salvou"}}]})
    fake_http(comp)

    data = asyncio.get_event_loop().run_until_complete(
        orm.chat([{"role": "user", "content": "oi"}], key="chave-real"))
    check(len(chamadas) == 2, "tentou o OpenRouter primeiro, depois o local")
    check(data["_provider"] == "ollama", "informa que quem respondeu foi o local")


def test_sem_fallback_falha_honesto():
    print("\n10. sem chave e sem fallback: erro claro, não silêncio")
    import asyncio
    config.settings.ollama_base = ""
    config.settings.ollama_model = ""
    try:
        asyncio.get_event_loop().run_until_complete(
            orm.chat([{"role": "user", "content": "oi"}], key=""))
        check(False, "deveria ter levantado")
    except ValueError as exc:
        check("chave" in str(exc).lower(), "explica que falta a chave")


# ============================================================== WEBHOOK
def test_webhook_desligado():
    print("\n11. sem MESSAGING_SECRET o webhook fica desligado")
    zera()
    config.settings.messaging_secret = ""
    r = client.post("/api/messaging/telegram/qualquer", json={})
    check(r.status_code == 503, f"responde 503 (veio {r.status_code})")
    check("MESSAGING_SECRET" in r.json()["detail"], "diz o que configurar")


def test_webhook_segredo_errado():
    print("\n12. segredo errado é 404 — pra quem varre, a rota não existe")
    zera()
    config.settings.messaging_secret = "s3cr3t"
    config.settings.telegram_allowed_chats = "123"
    r = client.post("/api/messaging/telegram/chutando", json={})
    check(r.status_code == 404, f"404 e não 403 (veio {r.status_code})")


def test_webhook_sem_allowlist():
    print("\n13. sem allowlist, recusa tudo (negar é o padrão seguro)")
    zera()
    config.settings.messaging_secret = "s3cr3t"
    config.settings.telegram_allowed_chats = ""
    r = client.post("/api/messaging/telegram/s3cr3t", json={
        "message": {"chat": {"id": 999}, "text": "apaga tudo"}})
    check(r.status_code == 503, f"recusa (veio {r.status_code})")
    check("ALLOWED" in r.json()["detail"], "manda configurar a allowlist")


def test_webhook_autorizacao():
    print("\n14. só quem está na allowlist é atendido")
    zera()
    config.settings.messaging_secret = "s3cr3t"
    config.settings.telegram_allowed_chats = "123,456"
    config.settings.telegram_bot_token = ""
    respondeu = {"n": 0}

    async def fake_responde(pergunta):
        respondeu["n"] += 1
        return "resposta do jarvis"
    msg_mod._responde = fake_responde

    r = client.post("/api/messaging/telegram/s3cr3t", json={
        "message": {"chat": {"id": 999}, "text": "oi"}})
    check(r.json().get("ignored") == "chat não autorizado", "chat de fora é ignorado")
    check(respondeu["n"] == 0, "e o modelo nem é chamado")

    r = client.post("/api/messaging/telegram/s3cr3t", json={
        "message": {"chat": {"id": 123}, "text": "oi"}})
    check(r.json()["answer"] == "resposta do jarvis", "chat autorizado é atendido")
    check(respondeu["n"] == 1, "o modelo foi chamado uma vez")

    r = client.post("/api/messaging/telegram/s3cr3t", json={
        "message": {"chat": {"id": 123}, "text": "   "}})
    check(r.json().get("ignored") == "sem texto", "mensagem vazia é ignorada")


def test_webhook_discord():
    print("\n15. Discord segue a mesma regra")
    zera()
    config.settings.messaging_secret = "s3cr3t"
    config.settings.discord_allowed_users = "u-1"
    config.settings.discord_webhook_url = ""

    r = client.post("/api/messaging/discord/s3cr3t",
                    json={"user_id": "invasor", "content": "roda format c:"})
    check(r.json().get("ignored") == "usuário não autorizado", "usuário de fora ignorado")
    r = client.post("/api/messaging/discord/s3cr3t",
                    json={"user_id": "u-1", "content": "oi"})
    check(r.json()["answer"] == "resposta do jarvis", "usuário autorizado atendido")


def test_status_protegido():
    print("\n16. /messaging/status exige token de sessão")
    zera()
    check(client.get("/api/messaging/status").status_code in (401, 403),
          "sem token não passa")
    j = client.get("/api/messaging/status", headers=SESSION).json()
    check(j["secret_configurado"] is True, "informa o que está pronto")
    check("s3cr3t" not in json.dumps(j), "sem expor o segredo")
    check("13.3" in j["nota"], "lembra que confirmação não passa pelo chat")


for fn in [test_analytics, test_analytics_log_adulterado, test_analytics_vazio,
           test_export_sem_token_de_agente, test_import_merge_e_replace,
           test_import_valida, test_import_nao_restaura_pareamento,
           test_ollama_sem_chave, test_ollama_quando_openrouter_cai,
           test_sem_fallback_falha_honesto,
           test_webhook_desligado, test_webhook_segredo_errado,
           test_webhook_sem_allowlist, test_webhook_autorizacao,
           test_webhook_discord, test_status_protegido]:
    fn()

print("\n" + ("TODOS OS TESTES PASSARAM" if not _fails else f"{_fails} FALHA(S)"))
sys.exit(1 if _fails else 0)
