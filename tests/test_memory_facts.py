"""Teste da extração de fatos, camada diária e busca na memória.

Roda sem pytest:  python3 tests/test_memory_facts.py

Sem rede: stub do `chat` (extrator/resumidor) e do provedor de embeddings.

O que estas features precisam garantir:
  - fato durável vira nó+aresta; conversa sem fato durável não polui o grafo
  - o mesmo fato dito de outro jeito NÃO duplica (dedup por slug)
  - relação funcional CORRIGE o fato antigo em vez de acumular contradição
  - nó órfão depois da correção é removido, e o vetor dele também
  - extrator quebrado ou JSON inválido não derruba a conversa
  - a camada diária só junta os fatos DAQUELE dia
  - a busca diz a verdade sobre o que fez: semantic vs lexical
  - vetor de outro modelo de embedding não é comparado como se fosse do mesmo
"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

import app.db as db  # noqa: E402

db._DB_PATH = Path(tempfile.mkdtemp()) / "test-facts.db"
os.environ["BACKEND_TOKEN"] = "seg"
import app.config as config  # noqa: E402

config.settings.backend_token = "seg"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app import embeddings, memory_facts  # noqa: E402
from app.routers import catalog as cat_mod  # noqa: E402
from app.routers import memory as mem_mod  # noqa: E402
from app import security as sec_mod  # noqa: E402

db.init_db()          # o lifespan só roda na 1ª requisição; limpa() vem antes

SESSION = {"X-Backend-Token": "seg", "X-OR-Key": "k"}
_fails = 0


def check(cond, label):
    global _fails
    print(("  ok  " if cond else " FAIL ") + label)
    if not cond:
        _fails += 1


# catálogo com um grátis, pra haver extrator disponível
cat_mod._cache["models"] = [
    {"id": "deepseek/deepseek-r1:free", "pricing": {"prompt": "0", "completion": "0"}},
]
cat_mod._cache["at"] = time.time()

client = TestClient(app)


def zera_rate():
    """O backend limita 30 req/5min por IP. A suíte passa disso — zerar a janela
    mantém o limitador ativo em produção e só evita 429 no meio do teste."""
    sec_mod._hits.clear()


def limpa():
    zera_rate()
    with db.get_conn() as conn:
        for t in ("memory_nodes", "memory_edges", "memory_daily", "memory_vectors"):
            conn.execute(f"DELETE FROM {t}")


def stub_extrator(fatos, cru=None, explode=False):
    async def fake(messages, key, model=None, tools=None, plugins=None):
        if explode:
            raise RuntimeError("extrator fora do ar")
        if cru is not None:
            return {"choices": [{"message": {"content": cru}}]}
        # o resumidor da camada diária cai aqui também; devolve texto simples
        if "parágrafo curto" in messages[0]["content"]:
            return {"choices": [{"message": {"content": "Resumo do dia."}}]}
        return {"choices": [{"message": {"content": json.dumps({"fatos": fatos})}}]}
    memory_facts.chat = fake
    mem_mod.chat = fake


def grafo():
    return client.get("/api/memory", headers=SESSION).json()


CONVERSA = [{"role": "user", "content": "moro em Belém e trabalho como desenvolvedor"}]


# ------------------------------------------------------- 1. extração básica
def test_extrai():
    print("\n1. fato durável vira nó e aresta")
    limpa()
    stub_extrator([
        {"sujeito": "Victor", "tipo_sujeito": "pessoa", "relacao": "mora em",
         "objeto": "Belém", "tipo_objeto": "lugar"},
        {"sujeito": "Victor", "tipo_sujeito": "pessoa", "relacao": "trabalha como",
         "objeto": "desenvolvedor", "tipo_objeto": "fato"},
    ])
    r = client.post("/api/memory/extract", headers=SESSION, json={"messages": CONVERSA})
    j = r.json()
    g = grafo()
    check(j["extraidos"] == 2, "extraiu os 2 fatos")
    check(len(g["nodes"]) == 3, f"criou 3 nós: Victor, Belém, desenvolvedor (veio {len(g['nodes'])})")
    check(any(n["id"] == "victor" and n["type"] == "pessoa" for n in g["nodes"]),
          "tipo do nó é respeitado")
    check(any(n["id"] == "belem" for n in g["nodes"]), "slug remove acento (Belém -> belem)")
    check(len(g["edges"]) == 2, "criou as 2 arestas")


def test_sem_fato():
    print("\n2. conversa sem fato durável não polui o grafo")
    limpa()
    stub_extrator([])
    r = client.post("/api/memory/extract", headers=SESSION,
                    json={"messages": [{"role": "user", "content": "como faço um for em python?"}]})
    check(r.json()["extraidos"] == 0, "não extraiu nada")
    check(len(grafo()["nodes"]) == 0, "grafo segue vazio")
    check(r.json()["ok"] is True, "e isso é sucesso, não erro")


# ------------------------------------------------------------- 3. dedup
def test_dedup():
    print("\n3. mesmo fato dito de outro jeito não duplica")
    limpa()
    stub_extrator([{"sujeito": "Victor", "tipo_sujeito": "pessoa", "relacao": "mora em",
                    "objeto": "Belém", "tipo_objeto": "lugar"}])
    client.post("/api/memory/extract", headers=SESSION, json={"messages": CONVERSA})
    stub_extrator([{"sujeito": "victor", "tipo_sujeito": "pessoa", "relacao": "mora em",
                    "objeto": "BELEM", "tipo_objeto": "lugar"}])
    client.post("/api/memory/extract", headers=SESSION, json={"messages": CONVERSA})
    g = grafo()
    check(len(g["nodes"]) == 2, f"continuam 2 nós, não 4 (veio {len(g['nodes'])})")
    check(len(g["edges"]) == 1, f"continua 1 aresta (veio {len(g['edges'])})")


# ------------------------------------------- 4. relação funcional corrige
def test_funcional_corrige():
    print("\n4. relação funcional corrige o fato antigo")
    limpa()
    stub_extrator([{"sujeito": "Victor", "tipo_sujeito": "pessoa", "relacao": "mora em",
                    "objeto": "Ananindeua", "tipo_objeto": "lugar"}])
    client.post("/api/memory/extract", headers=SESSION, json={"messages": CONVERSA})
    check(any(n["id"] == "ananindeua" for n in grafo()["nodes"]), "gravou a cidade antiga")

    stub_extrator([{"sujeito": "Victor", "tipo_sujeito": "pessoa", "relacao": "mora em",
                    "objeto": "Belém", "tipo_objeto": "lugar"}])
    r = client.post("/api/memory/extract", headers=SESSION, json={"messages": CONVERSA})
    g = grafo()
    moras = [e for e in g["edges"] if e["relation"] == "mora em"]
    check(len(moras) == 1, f"só UMA cidade fica (veio {len(moras)})")
    check(moras[0]["target"] == "belem", "a cidade nova substituiu a antiga")
    check(not any(n["id"] == "ananindeua" for n in g["nodes"]),
          "nó órfão da cidade antiga foi removido")
    check("ananindeua" in r.json()["aplicados"]["nos_removidos"], "a resposta reporta a remoção")

    with db.get_conn() as conn:
        sobrou = conn.execute(
            "SELECT COUNT(*) c FROM memory_vectors WHERE kind='node' AND ref='ananindeua'"
        ).fetchone()["c"]
    check(sobrou == 0, "o vetor do nó removido também saiu")


def test_nao_funcional_acumula():
    print("\n5. relação NÃO funcional acumula (não é contradição)")
    limpa()
    for proj in ("VTZ OS", "FPS Boost"):
        stub_extrator([{"sujeito": "Victor", "tipo_sujeito": "pessoa", "relacao": "trabalha em",
                        "objeto": proj, "tipo_objeto": "projeto"}])
        client.post("/api/memory/extract", headers=SESSION, json={"messages": CONVERSA})
    arestas = [e for e in grafo()["edges"] if e["relation"] == "trabalha em"]
    check(len(arestas) == 2, f"os dois projetos coexistem (veio {len(arestas)})")


# ------------------------------------------------ 6. extrator com problema
def test_extrator_ruim():
    print("\n6. extrator quebrado ou JSON inválido não derruba nada")
    limpa()
    stub_extrator(None, explode=True)
    r = client.post("/api/memory/extract", headers=SESSION, json={"messages": CONVERSA})
    check(r.status_code == 200 and r.json()["extraidos"] == 0, "falha do extrator = 0 fatos, sem erro")

    stub_extrator(None, cru="isso não é json")
    r = client.post("/api/memory/extract", headers=SESSION, json={"messages": CONVERSA})
    check(r.status_code == 200 and r.json()["extraidos"] == 0, "JSON inválido = 0 fatos")

    stub_extrator(None, cru=json.dumps({"fatos": [{"sujeito": "só isso"}, "texto solto", 42]}))
    r = client.post("/api/memory/extract", headers=SESSION, json={"messages": CONVERSA})
    check(r.json()["extraidos"] == 0, "tripla incompleta é descartada")
    check(len(grafo()["nodes"]) == 0, "e nada entra no grafo")


# ------------------------------------------------------- 7. camada diária
def test_diaria():
    print("\n7. camada diária junta só os fatos daquele dia")
    limpa()
    stub_extrator([{"sujeito": "Victor", "tipo_sujeito": "pessoa", "relacao": "mora em",
                    "objeto": "Belém", "tipo_objeto": "lugar"}])
    client.post("/api/memory/extract", headers=SESSION, json={"messages": CONVERSA})

    # planta um fato de ontem, direto no banco
    ontem_ts = time.time() - 86400
    ontem = datetime.fromtimestamp(ontem_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    hoje = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO memory_nodes (user_id, node_id, label, type, created_at) "
            "VALUES ('victor','fato-antigo','Coisa de ontem','fato',?)", (ontem_ts,))

    r = client.post("/api/memory/daily", headers=SESSION, json={"day": hoje})
    j = r.json()
    check(j["ok"] and j["summary"], "gerou resumo de hoje")
    check(j["fact_count"] >= 1, "contou os fatos de hoje")
    check("Coisa de ontem" not in (j["summary"] or ""), "fato de ontem NÃO entra no resumo de hoje")

    r2 = client.post("/api/memory/daily", headers=SESSION, json={"day": ontem})
    check(r2.json()["fact_count"] == 1, "o dia de ontem tem o seu próprio fato")

    dias = client.get("/api/memory/daily", headers=SESSION).json()["days"]
    check(len(dias) == 2, f"os dois dias ficam guardados (veio {len(dias)})")
    check(dias[0]["day"] > dias[1]["day"], "listados do mais recente pro mais antigo")


def test_diaria_dia_vazio():
    print("\n8. dia sem fato: diz que não há, não inventa resumo")
    limpa()
    r = client.post("/api/memory/daily", headers=SESSION, json={"day": "2020-01-01"})
    j = r.json()
    check(j["summary"] is None, "não devolve resumo")
    check("nenhum fato" in j.get("note", ""), "explica o motivo")


# ---------------------------------------------------------- 9. busca léxica
def test_busca_lexica():
    print("\n9. sem provedor de embeddings: busca léxica, e diz que é léxica")
    limpa()
    config.settings.embeddings_base = ""
    config.settings.embeddings_model = ""
    stub_extrator([{"sujeito": "Victor", "tipo_sujeito": "pessoa", "relacao": "mora em",
                    "objeto": "Belém do Pará", "tipo_objeto": "lugar"}])
    client.post("/api/memory/extract", headers=SESSION, json={"messages": CONVERSA})

    r = client.get("/api/memory/search?q=belem", headers=SESSION).json()
    check(r["mode"] == "lexical", "declara modo léxico")
    check("semântica" in r.get("note", ""), "explica como ter busca semântica")
    check(any("Belém" in x["text"] for x in r["results"]), "acha pelo termo")

    vazio = client.get("/api/memory/search?q=quantica", headers=SESSION).json()
    check(vazio["results"] == [], "termo sem relação não traz resultado forçado")


# ------------------------------------------------------- 10. busca semântica
def test_busca_semantica():
    print("\n10. com provedor: busca semântica de verdade")
    limpa()
    config.settings.embeddings_base = "http://fake/v1"
    config.settings.embeddings_model = "fake-embed"

    # vetores de brinquedo: 'cachorro' e 'cão' próximos; 'planilha' longe
    MAPA = {
        "cachorro": [1.0, 0.0, 0.0], "cao": [0.96, 0.1, 0.0],
        "planilha": [0.0, 1.0, 0.0], "gato": [0.8, 0.0, 0.4],
    }

    def vetor_de(texto):
        t = embeddings.tokens(texto)
        for chave, v in MAPA.items():
            if chave in t:
                return v
        return [0.0, 0.0, 1.0]

    async def fake_embed(textos):
        return [vetor_de(t) for t in textos], "fake-embed"
    embeddings.embed = fake_embed

    stub_extrator([
        {"sujeito": "Victor", "tipo_sujeito": "pessoa", "relacao": "tem",
         "objeto": "cachorro", "tipo_objeto": "fato"},
        {"sujeito": "Victor", "tipo_sujeito": "pessoa", "relacao": "usa",
         "objeto": "planilha", "tipo_objeto": "fato"},
    ])
    client.post("/api/memory/extract", headers=SESSION, json={"messages": CONVERSA})

    r = client.get("/api/memory/search?q=cao", headers=SESSION).json()
    check(r["mode"] == "semantic", f"declara modo semântico (veio {r['mode']})")
    check(r["results"], "trouxe resultado")
    check("cachorro" in r["results"][0]["text"],
          f"'cao' achou 'cachorro' — sinônimo, o que o léxico NÃO faz "
          f"(1º foi {r['results'][0]['text'] if r['results'] else '-'})")
    lex = embeddings.lexical_score("cao", "cachorro (fato)")
    check(lex < 0.2, f"confirmando: o léxico daria escore baixo pro mesmo par ({lex:.2f})")


def test_modelo_diferente():
    zera_rate()
    print("\n11. vetor de outro modelo não é comparado como se fosse do mesmo")
    with db.get_conn() as conn:
        conn.execute("UPDATE memory_vectors SET model = 'outro-embed'")
    r = client.get("/api/memory/search?q=cao", headers=SESSION).json()
    check(r["mode"] == "lexical", "não compara espaços diferentes")
    check("reindex" in r.get("warning", ""), "manda reindexar, explicando")

    ri = client.post("/api/memory/reindex", headers=SESSION).json()
    check(ri["ok"] and ri["mode"] == "semantic", "reindex volta pro semântico")
    r2 = client.get("/api/memory/search?q=cao", headers=SESSION).json()
    check(r2["mode"] == "semantic", "e a busca volta a ser semântica")


def test_provedor_cai():
    zera_rate()
    print("\n12. provedor de embeddings cai na hora da busca: avisa e não quebra")
    async def boom(textos):
        raise RuntimeError("timeout")
    embeddings.embed = boom
    r = client.get("/api/memory/search?q=cao", headers=SESSION).json()
    check(r["mode"] == "lexical", "cai no léxico")
    check("falhou" in r.get("warning", ""), "avisa que o provedor falhou")
    check(r["results"] is not None, "ainda responde")


for fn in [test_extrai, test_sem_fato, test_dedup, test_funcional_corrige,
           test_nao_funcional_acumula, test_extrator_ruim, test_diaria,
           test_diaria_dia_vazio, test_busca_lexica, test_busca_semantica,
           test_modelo_diferente, test_provedor_cai]:
    fn()

print("\n" + ("TODOS OS TESTES PASSARAM" if not _fails else f"{_fails} FALHA(S)"))
sys.exit(1 if _fails else 0)
