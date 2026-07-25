"""Teste do catálogo de modelos (/api/models).

Roda sem pytest:  python3 tests/test_catalog.py

Sem rede: substitui o cliente HTTP. Cobre o que importa nesta rota — que ela
não minta sobre a origem do dado:
  - busca no OpenRouter e enxuga o payload pro que o seletor usa
  - segunda chamada vem do cache, sem repetir a rede
  - refresh=true força ida nova
  - OpenRouter fora do ar COM cache: devolve o cache marcado como expirado,
    com aviso — não passa lista velha como atual
  - OpenRouter fora do ar SEM cache: 503 com o motivo, nunca lista vazia
    fingindo sucesso
"""
import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

import app.db as db  # noqa: E402

db._DB_PATH = Path(tempfile.mkdtemp()) / "test-catalog.db"
os.environ["BACKEND_TOKEN"] = "seg"
import app.config as config  # noqa: E402

config.settings.backend_token = "seg"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.routers import catalog as cat  # noqa: E402

SESSION = {"X-Backend-Token": "seg"}
_fails = 0
_idas = {"n": 0}


def check(cond, label):
    global _fails
    print(("  ok  " if cond else " FAIL ") + label)
    if not cond:
        _fails += 1


CATALOGO = {"data": [
    {"id": "openai/gpt-4.1", "name": "GPT-4.1",
     "pricing": {"prompt": "0.000002", "completion": "0.000008", "image": "0"},
     "context_length": 1047576, "created": 111, "extra_gigante": "x" * 500},
    {"id": "anthropic/claude-sonnet-5", "name": "Claude Sonnet 5",
     "pricing": {"prompt": "0.000002", "completion": "0.00001"},
     "context_length": 200000},
    {"name": "sem id — deve ser descartado"},
]}


class FakeResp:
    def __init__(self, payload, boom=False):
        self._p, self._boom = payload, boom

    def raise_for_status(self):
        if self._boom:
            raise RuntimeError("502 do upstream")

    def json(self):
        return self._p


class FakeClient:
    """Substitui httpx.AsyncClient. `modo` decide se responde ou explode."""
    modo = "ok"

    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False

    async def get(self, url, headers=None):
        _idas["n"] += 1
        if FakeClient.modo == "erro":
            raise RuntimeError("conexão recusada")
        if FakeClient.modo == "vazio":
            return FakeResp({"data": []})
        return FakeResp(CATALOGO)


cat.httpx.AsyncClient = FakeClient
client = TestClient(app)


def zera_cache():
    cat._cache["models"] = None
    cat._cache["at"] = 0.0
    _idas["n"] = 0


def test_busca_e_enxuga():
    print("\n1. busca no OpenRouter e enxuga o payload")
    zera_cache()
    FakeClient.modo = "ok"
    r = client.get("/api/models", headers=SESSION)
    j = r.json()
    check(r.status_code == 200, "responde 200")
    check(j["source"] == "openrouter", "diz que veio do OpenRouter")
    check(j["count"] == 2, f"descarta entrada sem id (count={j['count']})")
    m = j["data"][0]
    check(set(m.keys()) == {"id", "name", "pricing", "context_length", "architecture", "created"},
          f"guarda só os campos do seletor (veio {sorted(m.keys())})")
    check("extra_gigante" not in m, "não carrega o resto do payload do OpenRouter")
    check(m["pricing"] == {"prompt": "0.000002", "completion": "0.000008"},
          "preço fica só com entrada e saída")


def test_cache():
    print("\n2. segunda chamada vem do cache, sem repetir a rede")
    zera_cache()
    FakeClient.modo = "ok"
    client.get("/api/models", headers=SESSION)
    idas_apos_primeira = _idas["n"]
    r = client.get("/api/models", headers=SESSION)
    j = r.json()
    check(j["source"] == "cache", "marca a origem como cache")
    check(_idas["n"] == idas_apos_primeira, "não foi à rede de novo")
    check(j["count"] == 2, "mesma lista")


def test_refresh():
    print("\n3. refresh=true força ida nova")
    zera_cache()
    FakeClient.modo = "ok"
    client.get("/api/models", headers=SESSION)
    antes = _idas["n"]
    r = client.get("/api/models?refresh=true", headers=SESSION)
    check(_idas["n"] == antes + 1, "buscou de novo")
    check(r.json()["source"] == "openrouter", "origem volta a ser OpenRouter")


def test_erro_com_cache():
    print("\n4. upstream fora do ar COM cache: entrega o velho, avisando")
    zera_cache()
    FakeClient.modo = "ok"
    client.get("/api/models", headers=SESSION)          # aquece o cache
    FakeClient.modo = "erro"
    r = client.get("/api/models?refresh=true", headers=SESSION)
    j = r.json()
    check(r.status_code == 200, "ainda responde 200 (tem dado pra dar)")
    check(j["source"] == "cache_expirado", "não finge que está fresco")
    check("warning" in j and "inacess" in j["warning"], "explica que o OpenRouter caiu")
    check(j["count"] == 2, "entrega a lista que tinha")


def test_erro_sem_cache():
    print("\n5. upstream fora do ar SEM cache: 503, não lista vazia")
    zera_cache()
    FakeClient.modo = "erro"
    r = client.get("/api/models", headers=SESSION)
    check(r.status_code == 503, f"responde 503 (veio {r.status_code})")
    check("catálogo" in r.json()["detail"].lower(), "diz o que falhou")

    print("\n6. catálogo vazio também é falha, não sucesso")
    zera_cache()
    FakeClient.modo = "vazio"
    r = client.get("/api/models", headers=SESSION)
    check(r.status_code == 503, f"responde 503 (veio {r.status_code})")


def test_exige_token():
    print("\n7. rota é protegida pelo token de sessão")
    zera_cache()
    FakeClient.modo = "ok"
    r = client.get("/api/models")
    check(r.status_code in (401, 403), f"sem token não passa (veio {r.status_code})")


for fn in [test_busca_e_enxuga, test_cache, test_refresh,
           test_erro_com_cache, test_erro_sem_cache, test_exige_token]:
    fn()

print("\n" + ("TODOS OS TESTES PASSARAM" if not _fails else f"{_fails} FALHA(S)"))
sys.exit(1 if _fails else 0)
