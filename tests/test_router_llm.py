"""Teste do RouteLLM no backend (route=auto | free | fusion).

Roda sem pytest:  python3 tests/test_router_llm.py

Sem rede: stub de `chat` (classificador e fusor) e de `chat_stream` (a resposta).
Cobre o que o roteamento precisa garantir:
  - auto escolhe um modelo da shortlist e usa ELE na conversa
  - free só oferece modelos grátis ao classificador
  - id alucinado pelo classificador é descartado (cai no padrão, não usa id falso)
  - classificador quebrado não derruba o chat
  - catálogo indisponível não derruba o chat
  - fusion pede aos dois modelos EM PARALELO e funde
  - fusion com um só respondendo entrega sem fundir, avisando
  - sem route, nada disso roda (o modelo pedido é respeitado)
  - o classificador é sempre um modelo grátis (roteamento não custa)
"""
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

import app.db as db  # noqa: E402

db._DB_PATH = Path(tempfile.mkdtemp()) / "test-router.db"
os.environ["BACKEND_TOKEN"] = "seg"
import app.config as config  # noqa: E402

config.settings.backend_token = "seg"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.routers import agent as agent_mod  # noqa: E402
from app.routers import catalog as cat_mod  # noqa: E402
from app import router_llm  # noqa: E402

SESSION = {"X-Backend-Token": "seg", "X-OR-Key": "k"}
_fails = 0


def check(cond, label):
    global _fails
    print(("  ok  " if cond else " FAIL ") + label)
    if not cond:
        _fails += 1


CATALOGO = [
    {"id": "anthropic/claude-opus-4.8", "name": "Opus",
     "pricing": {"prompt": "0.000005", "completion": "0.000025"}},
    {"id": "anthropic/claude-sonnet-5", "name": "Sonnet",
     "pricing": {"prompt": "0.000002", "completion": "0.00001"}},
    {"id": "openai/gpt-5.5", "name": "GPT",
     "pricing": {"prompt": "0.000005", "completion": "0.00003"}},
    {"id": "deepseek/deepseek-r1:free", "name": "R1 free",
     "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "meta-llama/llama-3.3-70b:free", "name": "Llama free",
     "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "google/gemini-2.5-flash", "name": "Flash",
     "pricing": {"prompt": "0.0000003", "completion": "0.0000012"}},
    {"id": "black-forest-labs/flux", "name": "Flux",
     "pricing": {"prompt": "0", "completion": "0"},
     "architecture": {"output_modalities": ["image"]}},
]


def usa_catalogo(itens=CATALOGO):
    cat_mod._cache["models"] = itens
    cat_mod._cache["at"] = time.time()


def sem_catalogo():
    cat_mod._cache["models"] = None
    cat_mod._cache["at"] = 0.0

    class Boom:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): raise RuntimeError("rede fora")
    cat_mod.httpx.AsyncClient = Boom


def events(resp):
    return [json.loads(l) for l in resp.text.splitlines() if l.strip()]


def first(evs, t):
    return next((e for e in evs if e["type"] == t), None)


client = TestClient(app)
_visto = {}


def stub_resposta(texto="ok"):
    """chat_stream que registra com que modelo foi chamado."""
    async def fake(messages, key, model=None, tools=None):
        _visto["modelo_da_conversa"] = model
        yield {"type": "token", "text": texto}
        yield {"type": "finish", "reason": "stop"}
    agent_mod.chat_stream = fake


def stub_classificador(escolha, capturar_prompt=False, explode=False):
    """chat que responde como o classificador."""
    async def fake(messages, key, model=None, tools=None, plugins=None):
        if explode:
            raise RuntimeError("classificador fora do ar")
        _visto["modelo_classificador"] = model
        if capturar_prompt:
            _visto["prompt"] = messages[0]["content"]
        return {"choices": [{"message": {"content": json.dumps({"model": escolha})}}]}
    router_llm.chat = fake


# ------------------------------------------------------------------ 1. auto
def test_auto():
    print("\n1. route=auto: classifica e usa o modelo escolhido")
    usa_catalogo()
    _visto.clear()
    stub_classificador("anthropic/claude-sonnet-5", capturar_prompt=True)
    stub_resposta("Resposta do Sonnet.")

    r = client.post("/api/agent", headers=SESSION, json={
        "messages": [{"role": "user", "content": "refatora esse módulo"}],
        "stream": True, "route": "auto"})
    evs = events(r)
    rota = first(evs, "route")
    check(rota and rota["mode"] == "auto", "emite evento route com o modo")
    check(rota and rota.get("model") == "anthropic/claude-sonnet-5",
          "informa o modelo escolhido ao painel")
    check(_visto.get("modelo_da_conversa") == "anthropic/claude-sonnet-5",
          f"a conversa roda no modelo escolhido (rodou em {_visto.get('modelo_da_conversa')})")
    check(first(evs, "done")["answer"] == "Resposta do Sonnet.", "resposta chega normal")
    p = _visto.get("prompt", "")
    check("black-forest-labs/flux" not in p, "modelo de imagem não entra na shortlist")
    check("anthropic/claude-opus-4.8" in p, "modelo forte entra na shortlist")


# ------------------------------------------------------------------ 2. free
def test_free():
    print("\n2. route=free: só modelos grátis são oferecidos")
    usa_catalogo()
    _visto.clear()
    stub_classificador("deepseek/deepseek-r1:free", capturar_prompt=True)
    stub_resposta("Resposta grátis.")

    r = client.post("/api/agent", headers=SESSION, json={
        "messages": [{"role": "user", "content": "resume isso"}],
        "stream": True, "route": "free"})
    evs = events(r)
    p = _visto.get("prompt", "")
    check(first(evs, "route").get("model") == "deepseek/deepseek-r1:free",
          "escolhe um grátis")
    check("anthropic/claude-opus-4.8" not in p, "modelo pago NÃO é oferecido")
    check("deepseek/deepseek-r1:free" in p and "meta-llama/llama-3.3-70b:free" in p,
          "os grátis de texto são oferecidos")
    check("black-forest-labs/flux" not in p, "grátis de imagem fica fora")
    check(_visto.get("modelo_da_conversa") == "deepseek/deepseek-r1:free",
          "conversa roda no grátis escolhido")


# --------------------------------------------------- 3. classificador alucina
def test_id_inventado():
    print("\n3. classificador devolve id que não existe: descarta a escolha")
    usa_catalogo()
    _visto.clear()
    stub_classificador("modelo/que-nao-existe")
    stub_resposta()

    r = client.post("/api/agent", headers=SESSION, json={
        "messages": [{"role": "user", "content": "oi"}],
        "model": "openai/gpt-5.5", "stream": True, "route": "auto"})
    evs = events(r)
    rota = first(evs, "route")
    check(rota.get("fallback") is True, "marca que caiu no padrão")
    check("model" not in rota, "não anuncia modelo escolhido")
    check(_visto.get("modelo_da_conversa") == "openai/gpt-5.5",
          f"usa o modelo do pedido, não o inventado (usou {_visto.get('modelo_da_conversa')})")
    check(first(evs, "done") is not None, "conversa segue normalmente")


# ------------------------------------------- 4. classificador fora do ar
def test_classificador_quebrado():
    print("\n4. classificador quebrado: não derruba o chat")
    usa_catalogo()
    _visto.clear()
    stub_classificador(None, explode=True)
    stub_resposta("Segui sem roteador.")

    r = client.post("/api/agent", headers=SESSION, json={
        "messages": [{"role": "user", "content": "oi"}],
        "model": "openai/gpt-5.5", "stream": True, "route": "auto"})
    evs = events(r)
    check(first(evs, "route").get("fallback") is True, "avisa o fallback")
    check(first(evs, "error") is None, "não vira erro")
    check(first(evs, "done")["answer"] == "Segui sem roteador.", "responde igual")


# ------------------------------------------- 5. catálogo indisponível
def test_sem_catalogo():
    print("\n5. catálogo indisponível: segue no modelo padrão, avisando")
    sem_catalogo()
    _visto.clear()
    stub_resposta("Respondi mesmo assim.")

    r = client.post("/api/agent", headers=SESSION, json={
        "messages": [{"role": "user", "content": "oi"}],
        "model": "openai/gpt-5.5", "stream": True, "route": "auto"})
    evs = events(r)
    rota = first(evs, "route")
    check(rota and rota.get("fallback") is True, "avisa que não deu pra rotear")
    check("catálogo" in rota.get("note", ""), "explica o motivo")
    check(first(evs, "done")["answer"] == "Respondi mesmo assim.", "chat continua funcionando")


# ------------------------------------------------------------------ 6. fusion
def test_fusion():
    print("\n6. route=fusion: dois modelos em paralelo, fundidos")
    usa_catalogo()
    chamados = []
    ordem = []

    async def fake_chat(messages, key, model=None, tools=None, plugins=None):
        chamados.append(model)
        if "duas respostas independentes" in messages[0]["content"]:
            return {"choices": [{"message": {"content": "Resposta fundida."}}]}
        ordem.append(("inicio", model, time.perf_counter()))
        await asyncio.sleep(0.25)          # se fosse sequencial, somaria
        ordem.append(("fim", model, time.perf_counter()))
        return {"choices": [{"message": {"content": f"resposta de {model}"}}]}

    router_llm.chat = fake_chat
    t0 = time.perf_counter()
    r = client.post("/api/agent", headers=SESSION, json={
        "messages": [{"role": "user", "content": "compara as duas abordagens"}],
        "stream": True, "route": "fusion"})
    dur = time.perf_counter() - t0
    evs = events(r)

    rota = first(evs, "route")
    check(rota and rota["mode"] == "fusion", "emite route com modo fusion")
    check(rota and len(rota.get("models", [])) == 2, "anuncia os dois modelos")
    check(rota["models"][0] != rota["models"][1], "os dois modelos são distintos")
    check(first(evs, "done")["answer"] == "Resposta fundida.", "entrega a fusão")
    check(dur < 0.45, f"rodou em paralelo, não em série ({dur:.2f}s para 2x0.25s)")
    check(len(chamados) == 3, f"2 respostas + 1 fusão = 3 chamadas (foram {len(chamados)})")


def test_fusion_um_falha():
    print("\n7. fusion com um modelo falhando: entrega sem fundir, avisando")
    usa_catalogo()

    async def fake_chat(messages, key, model=None, tools=None, plugins=None):
        if "duas respostas independentes" in messages[0]["content"]:
            raise AssertionError("não deveria fundir com uma resposta só")
        if "opus" in (model or ""):
            raise RuntimeError("esse caiu")
        return {"choices": [{"message": {"content": "só eu respondi"}}]}

    router_llm.chat = fake_chat
    r = client.post("/api/agent", headers=SESSION, json={
        "messages": [{"role": "user", "content": "oi"}],
        "stream": True, "route": "fusion"})
    evs = events(r)
    rotas = [e for e in evs if e["type"] == "route"]
    check(any("só um dos modelos" in (e.get("note") or "") for e in rotas),
          "avisa que não fundiu")
    check(first(evs, "done")["answer"] == "só eu respondi", "entrega a que respondeu")


def test_fusion_ambos_falham():
    print("\n8. fusion com os dois falhando: erro honesto")
    usa_catalogo()

    async def fake_chat(messages, key, model=None, tools=None, plugins=None):
        raise RuntimeError("tudo fora")

    router_llm.chat = fake_chat
    r = client.post("/api/agent", headers=SESSION, json={
        "messages": [{"role": "user", "content": "oi"}],
        "stream": True, "route": "fusion"})
    evs = events(r)
    check(first(evs, "error") is not None, "emite error")
    check("respondeu" in first(evs, "error")["message"], "diz que ninguém respondeu")
    check(first(evs, "done") is None, "não finge sucesso")


# ------------------------------------------------- 9. sem route, nada muda
def test_sem_route():
    print("\n9. sem route: o modelo pedido é respeitado, nada é classificado")
    usa_catalogo()
    _visto.clear()

    async def nao_deve_chamar(*a, **k):
        raise AssertionError("classificador não deveria ser chamado sem route")
    router_llm.chat = nao_deve_chamar
    stub_resposta("direto")

    r = client.post("/api/agent", headers=SESSION, json={
        "messages": [{"role": "user", "content": "oi"}],
        "model": "openai/gpt-5.5", "stream": True})
    evs = events(r)
    check(first(evs, "route") is None, "nenhum evento route")
    check(_visto.get("modelo_da_conversa") == "openai/gpt-5.5", "usa o modelo pedido")


# ------------------------------------- 10. classificador é sempre grátis
def test_classificador_gratis():
    print("\n10. o classificador é sempre um modelo grátis")
    usa_catalogo()
    _visto.clear()
    stub_classificador("anthropic/claude-sonnet-5")
    stub_resposta()
    client.post("/api/agent", headers=SESSION, json={
        "messages": [{"role": "user", "content": "oi"}],
        "stream": True, "route": "auto"})
    usado = _visto.get("modelo_classificador")
    livre = next(m for m in CATALOGO if m["id"] == usado)
    check(router_llm.is_free(livre), f"classificou com modelo grátis ({usado})")


for fn in [test_auto, test_free, test_id_inventado, test_classificador_quebrado,
           test_sem_catalogo, test_fusion, test_fusion_um_falha,
           test_fusion_ambos_falham, test_sem_route, test_classificador_gratis]:
    fn()

print("\n" + ("TODOS OS TESTES PASSARAM" if not _fails else f"{_fails} FALHA(S)"))
sys.exit(1 if _fails else 0)
