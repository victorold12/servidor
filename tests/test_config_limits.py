"""Teste do rate limit configurável e da resolução do endpoint de embeddings.

Roda sem pytest:  python3 tests/test_config_limits.py

Estes dois vieram de problemas reais encontrados testando:
  - o limite antigo (30 req/5min) era batido pelo uso normal do painel e pela
    própria suíte de testes;
  - configurar embeddings exigia repetir a URL do Ollama, que já estava no .env.
"""
import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

import app.db as db  # noqa: E402

db._DB_PATH = Path(tempfile.mkdtemp()) / "test-limits.db"
os.environ["BACKEND_TOKEN"] = "seg"
import app.config as config  # noqa: E402

config.settings.backend_token = "seg"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app import embeddings, security  # noqa: E402

db.init_db()
SESSION = {"X-Backend-Token": "seg"}
_fails = 0


def check(cond, label):
    global _fails
    print(("  ok  " if cond else " FAIL ") + label)
    if not cond:
        _fails += 1


client = TestClient(app)


def test_limite_padrao_serve_pro_uso_real():
    print("\n1. o padrão aguenta uma sessão de uso normal")
    check(config.settings.rate_limit >= 300,
          f"padrão folgado ({config.settings.rate_limit} por "
          f"{int(config.settings.rate_window)}s)")
    # uma interação do painel: catálogo + agente + extract + daily + search ≈ 5
    interacoes = config.settings.rate_limit // 5
    check(interacoes >= 60,
          f"dá pra ~{interacoes} interações na janela (antes eram 6)")


def test_limite_e_respeitado():
    print("\n2. o limite continua valendo — não foi só afrouxado")
    security._hits.clear()
    original = config.settings.rate_limit
    config.settings.rate_limit = 3
    try:
        codigos = [client.get("/api/analytics", headers=SESSION).status_code
                   for _ in range(5)]
        check(codigos[:3] == [200, 200, 200], f"as 3 primeiras passam ({codigos[:3]})")
        check(codigos[3] == 429, f"a 4ª é barrada ({codigos[3]})")
        r = client.get("/api/analytics", headers=SESSION)
        check("RATE_LIMIT" in r.json()["detail"],
              "a mensagem diz como aumentar, em vez de só reclamar")
        check("3 em" in r.json()["detail"], "e informa o limite atual")
    finally:
        config.settings.rate_limit = original
        security._hits.clear()


def test_janela_configuravel():
    print("\n3. a janela também é configurável")
    security._hits.clear()
    lim, jan = config.settings.rate_limit, config.settings.rate_window
    # 1s é o piso: janela sub-segundo não é limite de verdade, e rate_limit()
    # grampeia nisso de propósito
    config.settings.rate_limit = 2
    config.settings.rate_window = 1.0
    try:
        client.get("/api/analytics", headers=SESSION)
        client.get("/api/analytics", headers=SESSION)
        check(client.get("/api/analytics", headers=SESSION).status_code == 429,
              "estoura dentro da janela")
        import time as _t
        _t.sleep(1.2)
        check(client.get("/api/analytics", headers=SESSION).status_code == 200,
              "libera quando a janela passa")

        # e o piso é real: pedir 0.1s não vira janela de 0.1s
        security._hits.clear()
        config.settings.rate_window = 0.1
        client.get("/api/analytics", headers=SESSION)
        client.get("/api/analytics", headers=SESSION)
        _t.sleep(0.3)
        check(client.get("/api/analytics", headers=SESSION).status_code == 429,
              "janela abaixo de 1s é elevada pro piso, não aceita como está")
    finally:
        config.settings.rate_limit, config.settings.rate_window = lim, jan
        security._hits.clear()


def test_health_sem_limite():
    print("\n4. /api/health não é limitado (auto-detecção do site depende dele)")
    security._hits.clear()
    lim = config.settings.rate_limit
    config.settings.rate_limit = 1
    try:
        codigos = [client.get("/api/health").status_code for _ in range(4)]
        check(all(c == 200 for c in codigos), f"todas passam ({codigos})")
    finally:
        config.settings.rate_limit = lim
        security._hits.clear()


def test_embeddings_herda_url_do_ollama():
    print("\n5. embeddings herdam a URL do Ollama (sem repetir no .env)")
    orig = (config.settings.embeddings_base, config.settings.embeddings_model,
            config.settings.ollama_base)
    try:
        config.settings.embeddings_base = ""
        config.settings.embeddings_model = ""
        config.settings.ollama_base = ""
        check(embeddings.configured() is False, "nada configurado = não configurado")

        config.settings.ollama_base = "http://localhost:11434/v1"
        check(embeddings.configured() is False,
              "só a URL do Ollama não basta — sem modelo não há o que chamar")

        config.settings.embeddings_model = "nomic-embed-text"
        check(embeddings.configured() is True,
              "com o modelo, herda a URL do Ollama e fica pronto")
        check(embeddings.base_url() == "http://localhost:11434/v1",
              f"usa a URL do Ollama (veio {embeddings.base_url()})")

        config.settings.embeddings_base = "https://api.openai.com/v1/"
        check(embeddings.base_url() == "https://api.openai.com/v1",
              "EMBEDDINGS_BASE explícito ganha, e a barra final sai")
    finally:
        (config.settings.embeddings_base, config.settings.embeddings_model,
         config.settings.ollama_base) = orig


def test_busca_declara_o_modo_certo():
    print("\n6. a busca declara lexical/semantic conforme a configuração real")
    security._hits.clear()
    orig = (config.settings.embeddings_base, config.settings.embeddings_model,
            config.settings.ollama_base)
    try:
        config.settings.embeddings_base = ""
        config.settings.embeddings_model = ""
        config.settings.ollama_base = ""
        j = client.get("/api/memory/search?q=teste", headers=SESSION).json()
        check(j["mode"] == "lexical", "sem provedor: lexical")
        check("EMBEDDINGS_BASE" in (j.get("note") or "") or "reindex" in (j.get("note") or ""),
              "e diz o que fazer pra ter semântica")
    finally:
        (config.settings.embeddings_base, config.settings.embeddings_model,
         config.settings.ollama_base) = orig
        security._hits.clear()


def test_env_example_documenta_tudo():
    print("\n7. .env.example cobre todas as configurações que existem")
    texto = (_REPO / ".env.example").read_text(encoding="utf-8")
    # nomes que o Settings expõe e que o usuário precisa poder configurar
    esperados = [
        "OPENROUTER_API_KEY", "DEFAULT_MODEL", "ALLOWED_ORIGINS", "BACKEND_TOKEN",
        "RATE_LIMIT", "RATE_WINDOW", "OLLAMA_BASE", "OLLAMA_MODEL",
        "EMBEDDINGS_BASE", "EMBEDDINGS_MODEL", "EMBEDDINGS_KEY",
        "MESSAGING_SECRET", "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHATS",
        "DISCORD_WEBHOOK_URL", "DISCORD_ALLOWED_USERS",
        "NOTION_TOKEN", "FIGMA_TOKEN", "GOOGLE_CLIENT_ID", "REPLICATE_API_KEY",
    ]
    faltando = [e for e in esperados if e not in texto]
    check(not faltando, f"nada faltando (faltou: {faltando})")

    # e o contrário: campo do Settings que ninguém documentou
    campos = set(config.Settings.model_fields)
    internos = {"openrouter_base", "site_title", "request_timeout",
                "google_redirect_uri", "google_client_secret"}
    nao_doc = [c for c in campos - internos if c.upper() not in texto]
    check(not nao_doc, f"nenhum campo indocumentado (faltou: {nao_doc})")


for fn in [test_limite_padrao_serve_pro_uso_real, test_limite_e_respeitado,
           test_janela_configuravel, test_health_sem_limite,
           test_embeddings_herda_url_do_ollama, test_busca_declara_o_modo_certo,
           test_env_example_documenta_tudo]:
    fn()

print("\n" + ("TODOS OS TESTES PASSARAM" if not _fails else f"{_fails} FALHA(S)"))
sys.exit(1 if _fails else 0)
