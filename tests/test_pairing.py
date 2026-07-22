"""Teste ponta a ponta do pareamento do Agente Local + auth no hub WebSocket.

Roda sem pytest (o repo não usa) — direto:  python3 tests/test_pairing.py
Usa um banco SQLite temporário; não toca no jarvis.db real.

Cobre o núcleo de segurança (docs/SEGURANCA-AGENTE-LOCAL.md):
  - fluxo RFC 8628: start -> poll(pending) -> confirm -> poll(approved+token)
  - confirm/deny exigem token de sessão (401 sem ele)
  - trava de brute-force do user_code (5 tentativas -> denied) — REGRESSÃO:
    já quebrou uma vez porque o incremento de attempts não commitava quando o
    handler levantava HTTPException dentro do `with db.get_conn()`.
  - deny explícito e trava reportam "denied" (distinto de "expired") pro agente
  - WebSocket /ws/agent aceita token válido e recusa inválido
  - revogar mata o token na hora
"""
import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

import app.db as db  # noqa: E402

db._DB_PATH = Path(tempfile.mkdtemp()) / "test.db"

os.environ["BACKEND_TOKEN"] = "sessao-secreta"
import app.config as config  # noqa: E402

config.settings.backend_token = "sessao-secreta"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.routers import agents_hub  # noqa: E402

SESSION = {"X-Backend-Token": "sessao-secreta"}
_fails = 0


def check(cond, label):
    global _fails
    print(("  ok  " if cond else " FAIL ") + label)
    if not cond:
        _fails += 1


def main():
    with TestClient(app) as client:
        print("== start ==")
        r = client.post("/api/pair/start", json={"name": "PC-VICTOR", "platform": "win32"})
        check(r.status_code == 200, "start responde 200")
        d = r.json()
        device_code, user_code = d["device_code"], d["user_code"]
        check(len(device_code) > 30, "device_code é longo/secreto")
        check("-" in user_code and len(user_code) == 9, f"user_code formatado: {user_code}")
        check(d["interval"] == 3 and d["expires_in"] == 600, "interval/expires corretos")

        print("== poll antes de confirmar ==")
        r = client.post("/api/pair/poll", json={"device_code": device_code})
        check(r.json()["status"] == "pending", "poll = pending")

        print("== auth de sessão em confirm ==")
        r = client.post("/api/pair/confirm", json={"user_code": user_code})
        check(r.status_code == 401, "confirm sem sessão = 401")
        r = client.post("/api/pair/confirm", json={"user_code": "AAAA-BBBB"}, headers=SESSION)
        check(r.status_code == 400, "código errado = 400")

        print("== confirm certo -> approved + token ==")
        r = client.post("/api/pair/confirm", json={"user_code": user_code}, headers=SESSION)
        check(r.status_code == 200 and r.json()["ok"] and r.json()["name"] == "PC-VICTOR", "confirm ok")
        d = client.post("/api/pair/poll", json={"device_code": device_code}).json()
        check(d["status"] == "approved", "poll = approved")
        check(len(d["agent_token"]) > 30 and d["agent_id"], "recebeu agent_id + agent_token")
        agent_token, agent_id = d["agent_token"], d["agent_id"]
        r = client.post("/api/pair/poll", json={"device_code": device_code})
        check(r.json()["status"] == "expired", "pending é one-shot (consumido)")

        print("== auth do agente + hub ==")
        check(agents_hub._authenticate_agent(agent_token) == agent_id, "token válido -> agent_id")
        check(agents_hub._authenticate_agent("token-falso") is None, "token falso -> None")
        r = client.get("/api/agents", headers=SESSION)
        agents = r.json()["agents"]
        check(len(agents) == 1 and agents[0]["online"] is False, "lista 1 agente, offline")

        print("== WebSocket ==")
        with client.websocket_connect(f"/ws/agent?token={agent_token}") as ws:
            ws.send_text('{"type":"heartbeat"}')
            check(True, "WS token válido conecta + heartbeat")
        try:
            with client.websocket_connect("/ws/agent?token=falso"):
                check(False, "WS token falso NÃO deveria conectar")
        except Exception:
            check(True, "WS token falso recusado")

        print("== revogar ==")
        r = client.post(f"/api/agents/{agent_id}/revoke", headers=SESSION)
        check(r.status_code == 200, "revoke ok")
        check(agents_hub._authenticate_agent(agent_token) is None, "token revogado não autentica")

        print("== trava de brute-force (regressão do commit) ==")
        r = client.post("/api/pair/start", json={"name": "PC2", "platform": "linux"})
        dc2 = r.json()["device_code"]
        for _ in range(5):
            client.post("/api/pair/confirm", json={"user_code": "ZZZZ-9999"}, headers=SESSION)
        check(client.post("/api/pair/poll", json={"device_code": dc2}).json()["status"] == "denied",
              "5 tentativas erradas -> denied (attempts persistiu)")
        check(client.post("/api/pair/poll", json={"device_code": dc2}).json()["status"] == "expired",
              "pending travado limpo no poll seguinte")

        print("== deny explícito ==")
        r = client.post("/api/pair/start", json={"name": "PC3", "platform": "darwin"})
        dc3, uc3 = r.json()["device_code"], r.json()["user_code"]
        check(client.post("/api/pair/deny", json={"user_code": uc3}, headers=SESSION).status_code == 200,
              "deny ok")
        check(client.post("/api/pair/poll", json={"device_code": dc3}).json()["status"] == "denied",
              "deny explícito -> poll = denied")
        r = client.post("/api/pair/start", json={"name": "PC4", "platform": "linux"})
        check(client.post("/api/pair/deny", json={"user_code": r.json()["user_code"]}).status_code == 401,
              "deny sem sessão = 401")

    if _fails:
        print(f"\n{_fails} CHECK(S) FALHARAM ✗")
        sys.exit(1)
    print("\nTODOS OS CHECKS PASSARAM ✓")


if __name__ == "__main__":
    main()
