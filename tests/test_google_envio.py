"""Enviar e-mail e mexer na agenda — as partes que dá pra provar sem o Google.

Sem pytest (`python3 tests/test_google_envio.py`), igual aos outros.

O QUE ESTE TESTE NÃO PROVA, e é bom estar escrito: que o Google aceita a
mensagem. Isso exige conta, consentimento e rede — nada disso existe aqui. O que
ele prova é tudo o que está do NOSSO lado e quebra calado:

  - a mensagem sai no formato que a API do Gmail exige (RFC 2822 em base64
    URL-SAFE, sem `=` no fim). Base64 comum é recusado com erro obscuro.
  - escopo faltando vira 403 com instrução, não 500 nem sucesso falso
  - vários destinatários de uma vez são recusados
  - evento sem hora de fim ganha uma hora, em vez de erro
  - evento leva timeZone junto (senão cai no fuso do calendário, e a reunião
    aparece três horas errada)
  - a sessão do Google sobrevive a reiniciar o processo
"""
import base64
import os
import sys
import tempfile
from email import message_from_bytes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["JARVIS_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="vtz-goog-"), "t.db")
os.environ.pop("RENDER", None)

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db, store  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import google  # noqa: E402

db.init_db()
cli = TestClient(app)
falhas = []


def checa(nome, cond, extra=""):
    print(("  ok  " if cond else "FALHA ") + nome + ("" if cond else f"  {extra!r}"))
    if not cond:
        falhas.append(nome)


# ---- dublê do Google: guarda o que foi enviado e responde como a API real ----
enviados = []


class RespostaFalsa:
    def __init__(self, corpo, status=200):
        self.status_code = status
        self._corpo = corpo
        self.text = str(corpo)

    def json(self):
        return self._corpo


class ClienteFalso:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        enviados.append({"url": url, "json": kw.get("json")})
        if "messages/send" in url:
            return RespostaFalsa({"id": "msg-1"})
        return RespostaFalsa({"id": "ev-1", "summary": kw["json"].get("summary"),
                              "start": kw["json"].get("start"),
                              "htmlLink": "https://calendar.google.com/x"})

    async def get(self, url, **kw):
        enviados.append({"url": url, "params": kw.get("params")})
        return RespostaFalsa({"items": [
            {"id": "a", "summary": "Reunião", "start": {"dateTime": "2026-08-02T15:00:00-03:00"},
             "end": {"dateTime": "2026-08-02T16:00:00-03:00"}, "htmlLink": "x"},
            {"id": "b", "summary": "Feriado", "start": {"date": "2026-08-05"},
             "end": {"date": "2026-08-06"}, "htmlLink": "y"},
        ]})


httpx.AsyncClient = lambda *a, **k: ClienteFalso()          # noqa: E305
google._token.update(access_token="tk", refresh_token="rt", expires_at=9e18)
store.set_secrets({"google_scopes": " ".join(google.SCOPES)})

print("— o e-mail sai no formato que a API do Gmail exige")
r = cli.post("/api/connectors/google/gmail/send",
             json={"to": "alguem@exemplo.com", "subject": "Teste", "body": "Corpo do e-mail."})
checa("aceitou", r.status_code == 200, r.text[:200])
cru = enviados[-1]["json"]["raw"]
checa("nada de '=' no fim (base64 url-safe)", not cru.endswith("="), cru[-8:])
checa("nem '+' ou '/' no meio", "+" not in cru and "/" not in cru, cru[:40])
# Desfaz o base64url e lê a mensagem: é a prova de que é RFC 2822 de verdade.
msg = message_from_bytes(base64.urlsafe_b64decode(cru + "=" * (-len(cru) % 4)))
checa("destinatário certo", msg["To"] == "alguem@exemplo.com", msg["To"])
checa("assunto certo", msg["Subject"] == "Teste", msg["Subject"])
checa("corpo certo", "Corpo do e-mail." in msg.get_payload(), msg.get_payload()[:60])
checa("assunto vazio vira '(sem assunto)'",
      cli.post("/api/connectors/google/gmail/send",
               json={"to": "a@b.com", "body": "x"}).json()["subject"] == "(sem assunto)")

print("— recusas que evitam estrago")
r = cli.post("/api/connectors/google/gmail/send",
             json={"to": "a@b.com, c@d.com", "body": "x"})
checa("vários destinatários de uma vez: recusado", r.status_code == 400, r.status_code)
checa("e o erro explica", "um de cada vez" in r.text.lower(), r.text[:140])
checa("endereço sem @: recusado",
      cli.post("/api/connectors/google/gmail/send",
               json={"to": "naoehemail", "body": "x"}).status_code == 400)
checa("corpo vazio: recusado",
      cli.post("/api/connectors/google/gmail/send",
               json={"to": "a@b.com", "body": ""}).status_code == 422)

print("— consentimento antigo não cobre os escopos novos")
store.set_secrets({"google_scopes": "https://www.googleapis.com/auth/gmail.readonly"})
st = cli.get("/api/connectors/google/status").json()
checa("o status avisa", st["precisa_reconectar"] is True, st)
checa("e diz quais faltam", any("gmail.send" in e for e in st["scopes_faltando"]), st["scopes_faltando"])
checa("o aviso é legível", "reconecte" in (st["aviso"] or "").lower(), st["aviso"])
r = cli.post("/api/connectors/google/gmail/send", json={"to": "a@b.com", "body": "x"})
checa("enviar dá 403, não 500 nem sucesso falso", r.status_code == 403, r.status_code)
checa("com instrução do que fazer", "reconecte" in r.text.lower(), r.text[:160])
r = cli.post("/api/connectors/google/calendar/events",
             json={"titulo": "x", "inicio": "2026-08-02T15:00"})
checa("criar evento também dá 403", r.status_code == 403, r.status_code)
store.set_secrets({"google_scopes": " ".join(google.SCOPES)})

print("— calendário")
r = cli.get("/api/connectors/google/calendar/events?days=7")
d = r.json()
checa("listou", r.status_code == 200 and d["count"] == 2, r.text[:160])
checa("evento com hora traz o horário", d["events"][0]["inicio"].startswith("2026-08-02T15"),
      d["events"][0])
checa("evento de dia inteiro NÃO some", d["events"][1]["inicio"] == "2026-08-05", d["events"][1])
checa("e é marcado como dia inteiro", d["events"][1]["dia_inteiro"] is True, d["events"][1])
params = enviados[-1]["params"]
checa("pede eventos expandidos (recorrente não vira 1 linha só)",
      params["singleEvents"] == "true", params)
checa("e em ordem de início", params["orderBy"] == "startTime", params)

r = cli.post("/api/connectors/google/calendar/events",
             json={"titulo": "Dentista", "inicio": "2026-08-02T15:00"})
checa("criou sem hora de fim", r.status_code == 200, r.text[:160])
corpo = enviados[-1]["json"]
checa("ganhou 1h de duração", corpo["end"]["dateTime"].startswith("2026-08-02T16:00"), corpo["end"])
checa("com fuso explícito", corpo["start"]["timeZone"] == "America/Sao_Paulo", corpo["start"])
checa("data sem sentido é recusada com motivo",
      cli.post("/api/connectors/google/calendar/events",
               json={"titulo": "x", "inicio": "amanha de tarde"}).status_code == 400)

print("— a sessão sobrevive a reiniciar o processo")
store.set_secrets({"google_refresh_token": "rt-guardado"})
google._token.clear()
google._carrega_sessao()
checa("recuperou o refresh_token do disco", google._token.get("refresh_token") == "rt-guardado",
      google._token)
checa("e o status diz que está conectado",
      cli.get("/api/connectors/google/status").json()["connected"] is True)

print("\n" + (f"{len(falhas)} FALHA(S): {', '.join(falhas)}" if falhas else "tudo passou"))
sys.exit(1 if falhas else 0)
