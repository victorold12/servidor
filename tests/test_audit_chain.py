"""Teste da cadeia de hash da auditoria (Seção 13.1 — verify_chain).

Roda sem pytest (o repo não usa):  python3 tests/test_audit_chain.py
Usa banco temporário; não toca no jarvis.db real.

Cobre:
  - escrita encadeia (prev_hash de cada linha = hash da anterior; 1ª = genesis)
  - verify passa numa cadeia íntegra
  - adulterar um campo no meio é detectado (broken_at aponta a linha)
  - apagar uma linha no meio é detectado
  - linhas legadas (pré-migração, hash NULL) são puladas e o resto verifica
  - endpoint /api/audit/verify responde e exige token de sessão
"""
import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

import app.db as db  # noqa: E402

db._DB_PATH = Path(tempfile.mkdtemp()) / "test-audit.db"

os.environ["BACKEND_TOKEN"] = "sessao-secreta"
import app.config as config  # noqa: E402

config.settings.backend_token = "sessao-secreta"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.routers import agents_hub as ah  # noqa: E402

SESSION = {"X-Backend-Token": "sessao-secreta"}
_fails = 0


def check(cond, label):
    global _fails
    print(("  ok  " if cond else " FAIL ") + label)
    if not cond:
        _fails += 1


def _write(n, agent="agent-1"):
    for i in range(n):
        ah._write_audit(agent, {
            "action_type": "fs_write", "target": f"/x/{i}.txt", "tier": 1,
            "decision": "auto", "result": "ok", "chat_id": "c1", "message_id": f"m{i}",
        })


def main():
    db.init_db()

    print("== escrita encadeia + verify limpo ==")
    _write(3)
    with db.get_conn() as c:
        rows = c.execute("SELECT id, prev_hash, hash FROM audit_log ORDER BY id").fetchall()
        check(rows[0]["prev_hash"] == ah._AUDIT_GENESIS, "1ª linha aponta pro genesis")
        check(rows[1]["prev_hash"] == rows[0]["hash"], "2ª aponta pro hash da 1ª")
        check(rows[2]["prev_hash"] == rows[1]["hash"], "3ª aponta pro hash da 2ª")
        res = ah.verify_audit_chain(c)
        check(res["ok"] and res["chained"] == 3, f"verify limpo ok: {res}")

    print("== adulteração de campo no meio é detectada ==")
    with db.get_conn() as c:
        c.execute("UPDATE audit_log SET target='/hackeado' WHERE id=2")
    with db.get_conn() as c:
        res = ah.verify_audit_chain(c)
        check(not res["ok"] and res["broken_at"] == 2, f"adulterar id=2 quebra: {res}")
        # conserta pro próximo teste
        c.execute("UPDATE audit_log SET target='/x/1.txt' WHERE id=2")
    with db.get_conn() as c:
        check(ah.verify_audit_chain(c)["ok"], "restaurado volta a verificar")

    print("== remover linha do meio é detectado ==")
    with db.get_conn() as c:
        c.execute("DELETE FROM audit_log WHERE id=2")
    with db.get_conn() as c:
        res = ah.verify_audit_chain(c)
        check(not res["ok"] and res["broken_at"] == 3, f"apagar id=2 quebra na id=3: {res}")

    print("== linhas legadas (hash NULL) são puladas ==")
    db._DB_PATH = Path(tempfile.mkdtemp()) / "test-audit-legacy.db"
    import sqlite3
    import time as _t
    c = sqlite3.connect(db._DB_PATH)
    c.execute(
        "CREATE TABLE audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL, "
        "ts REAL NOT NULL, action_type TEXT NOT NULL, target TEXT NOT NULL, tier INTEGER NOT NULL, "
        "decision TEXT NOT NULL, result TEXT NOT NULL, chat_id TEXT, message_id TEXT)"
    )
    for i in range(2):
        c.execute(
            "INSERT INTO audit_log (agent_id,ts,action_type,target,tier,decision,result) VALUES (?,?,?,?,?,?,?)",
            ("old", _t.time(), "run", f"legacy{i}", 1, "auto", "ok"),
        )
    c.commit()
    c.close()
    db.init_db()  # migra: adiciona colunas
    _write(2)
    with db.get_conn() as c:
        res = ah.verify_audit_chain(c)
        check(res["ok"] and res["legacy"] == 2 and res["chained"] == 2,
              f"2 legadas puladas, 2 novas verificadas: {res}")

    print("== endpoint /api/audit/verify ==")
    with TestClient(app) as client:
        r = client.get("/api/audit/verify", headers=SESSION)
        check(r.status_code == 200 and r.json()["ok"], f"verify autenticado ok: {r.json()}")
        r = client.get("/api/audit/verify")
        check(r.status_code == 401, "verify sem sessão = 401")

    if _fails:
        print(f"\n{_fails} CHECK(S) FALHARAM ✗")
        sys.exit(1)
    print("\nTODOS OS CHECKS PASSARAM ✓")


if __name__ == "__main__":
    main()
