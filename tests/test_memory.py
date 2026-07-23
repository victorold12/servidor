"""Teste do grafo de memória no backend (Seção 7 — fonte única).

Roda sem pytest:  python3 tests/test_memory.py
Banco temporário; não toca no jarvis.db real.

Cobre: GET vazio, PUT+GET round-trip, PUT substitui (não acumula), aresta órfã
descartada, teto de tamanho, e auth (401 sem sessão).
"""
import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

import app.db as db  # noqa: E402

db._DB_PATH = Path(tempfile.mkdtemp()) / "test-memory.db"

os.environ["BACKEND_TOKEN"] = "sessao-secreta"
import app.config as config  # noqa: E402

config.settings.backend_token = "sessao-secreta"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

SESSION = {"X-Backend-Token": "sessao-secreta"}
_fails = 0


def check(cond, label):
    global _fails
    print(("  ok  " if cond else " FAIL ") + label)
    if not cond:
        _fails += 1


def main():
    with TestClient(app) as client:
        print("== GET vazio ==")
        r = client.get("/api/memory", headers=SESSION)
        check(r.status_code == 200 and r.json() == {"nodes": [], "edges": []}, "grafo começa vazio")

        print("== PUT + GET round-trip ==")
        g = {
            "nodes": [
                {"id": "voce", "label": "Você", "type": "pessoa"},
                {"id": "sp", "label": "São Paulo", "type": "lugar"},
            ],
            "edges": [{"source": "voce", "relation": "mora em", "target": "sp"}],
        }
        r = client.put("/api/memory", json=g, headers=SESSION)
        check(r.json() == {"ok": True, "nodes": 2, "edges": 1}, "PUT confirma contagem")
        got = client.get("/api/memory", headers=SESSION).json()
        check(len(got["nodes"]) == 2 and len(got["edges"]) == 1, "GET devolve o que foi posto")
        check(got["edges"][0]["relation"] == "mora em", "relação preservada")

        print("== PUT substitui (não acumula) ==")
        g2 = {"nodes": [{"id": "voce", "label": "Você", "type": "pessoa"}], "edges": []}
        client.put("/api/memory", json=g2, headers=SESSION)
        got = client.get("/api/memory", headers=SESSION).json()
        check(len(got["nodes"]) == 1 and len(got["edges"]) == 0, "PUT substitui o grafo inteiro")

        print("== aresta órfã descartada ==")
        g3 = {"nodes": [{"id": "voce", "label": "Você", "type": "pessoa"}],
              "edges": [{"source": "voce", "relation": "x", "target": "fantasma"}]}
        r = client.put("/api/memory", json=g3, headers=SESSION)
        check(r.json()["edges"] == 0, "aresta pra nó inexistente não persiste")

        print("== teto de tamanho ==")
        big = {"nodes": [{"id": f"n{i}", "label": f"n{i}"} for i in range(2001)], "edges": []}
        r = client.put("/api/memory", json=big, headers=SESSION)
        check(r.json().get("ok") is False, "grafo grande demais é recusado")

        print("== auth ==")
        check(client.get("/api/memory").status_code == 401, "GET sem sessão = 401")
        check(client.put("/api/memory", json={"nodes": [], "edges": []}).status_code == 401, "PUT sem sessão = 401")

    if _fails:
        print(f"\n{_fails} CHECK(S) FALHARAM ✗")
        sys.exit(1)
    print("\nTODOS OS CHECKS PASSARAM ✓")


if __name__ == "__main__":
    main()
