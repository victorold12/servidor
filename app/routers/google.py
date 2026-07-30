"""/api/connectors/google/* — Gmail e Drive via OAuth2 (grátis).

Pré-requisito (você faz uma vez, sem custo):
1. console.cloud.google.com > crie um projeto.
2. Ative as APIs "Gmail API" e "Google Drive API".
3. Credenciais > criar "ID do cliente OAuth" tipo "App da Web".
4. Em "URIs de redirecionamento autorizados" coloque:
   http://localhost:8000/api/connectors/google/callback  (e a URL publicada)
5. Copie Client ID e Secret para o .env (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET).

Fluxo: abra /api/connectors/google/authorize -> loga no Google -> volta no
callback -> token guardado. Depois use os endpoints de gmail/drive.

Nota honesta: o token é guardado EM MEMÓRIA (some se o servidor reinicia). Para
produção, persista em banco/arquivo cifrado. Isto é um scaffold funcional, não
uma solução multiusuário.
"""
import asyncio
import base64
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..config import settings
from .. import store

router = APIRouter()

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    # ENVIAR e-mail. `gmail.send` só envia: não lê, não apaga, não mexe em
    # rascunho. Escopo mínimo pra tarefa — o Google trata escopo além do
    # necessário como motivo de recusa na verificação do app.
    "https://www.googleapis.com/auth/gmail.send",
    # Eventos do calendário (ler e criar). NÃO dá acesso à configuração do
    # calendário nem à lista de calendários alheios.
    "https://www.googleapis.com/auth/calendar.events",
    "openid", "email",
]

# Sessão em memória; o refresh_token e os escopos concedidos são espelhados no
# store pra sobreviver a um reinício do processo (ver _carrega_sessao).
_token: dict = {}


def _carrega_sessao():
    """Recupera a sessão gravada. Sem isto, todo deploy e todo acordar de
    hibernar exigiria refazer o login do Google — o que na prática mataria o uso
    de Gmail e Calendário, porque ninguém reconecta três vezes por semana."""
    rt = store.get_secret("google_refresh_token")
    if rt:
        _token.setdefault("refresh_token", rt)
        _token.setdefault("expires_at", 0)      # força um refresh na 1ª chamada


_carrega_sessao()


def _falta_escopo() -> list[str]:
    """Escopos que ESTE código precisa e o consentimento atual não tem.

    Existe porque acrescentar escopo invalida o consentimento anterior: o token
    velho continua valendo pros escopos velhos e devolve 403 nos novos. Sem
    detectar isso, o sintoma é "o envio de e-mail parou de funcionar do nada" —
    com o resto do Google funcionando normalmente.
    """
    concedidos = set((store.get_secret("google_scopes") or "").split())
    if not concedidos:
        return []                                # nunca conectou: não é o caso
    return [e for e in SCOPES if e.startswith("https://") and e not in concedidos]


def _require_config():
    if not (store.get_secret("google_client_id") and store.get_secret("google_client_secret")):
        raise HTTPException(
            status_code=400,
            detail="Google não configurado. Preencha Client ID e Client Secret na "
                   "aba Conectores do site (crie o app OAuth em console.cloud.google.com).",
        )


@router.get("/authorize")
def authorize():
    _require_config()
    params = {
        "client_id": store.get_secret("google_client_id"),
        "redirect_uri": store.get_secret("google_redirect_uri"),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    }
    return {"url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)}


@router.get("/callback")
async def callback(code: str | None = None, error: str | None = None):
    if error:
        return HTMLResponse(f"<h3>Login cancelado: {error}</h3>")
    if not code:
        raise HTTPException(status_code=400, detail="sem 'code' no callback")
    _require_config()
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": store.get_secret("google_client_id"),
                "client_secret": store.get_secret("google_client_secret"),
                "redirect_uri": store.get_secret("google_redirect_uri"),
                "grant_type": "authorization_code",
            },
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    data = resp.json()
    _token.update(
        access_token=data.get("access_token"),
        refresh_token=data.get("refresh_token", _token.get("refresh_token")),
        expires_at=time.time() + data.get("expires_in", 3600) - 60,
    )
    # `scope` vem do Google e diz o que ELE concedeu, que nem sempre é o que foi
    # pedido (o usuário pode desmarcar caixas na tela de consentimento).
    store.set_secrets({
        "google_refresh_token": _token.get("refresh_token") or "",
        "google_scopes": data.get("scope", " ".join(SCOPES)),
    })
    return HTMLResponse("<h3>Google conectado ✓ Pode fechar esta aba.</h3>")


async def _access_token() -> str:
    if not _token.get("access_token"):
        raise HTTPException(status_code=401, detail="Não conectado. Abra /api/connectors/google/authorize primeiro.")
    if time.time() < _token.get("expires_at", 0):
        return _token["access_token"]
    # expirou: tenta refresh
    if not _token.get("refresh_token"):
        raise HTTPException(status_code=401, detail="Token expirado e sem refresh_token. Reconecte.")
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "refresh_token": _token["refresh_token"],
                "client_id": store.get_secret("google_client_id"),
                "client_secret": store.get_secret("google_client_secret"),
                "grant_type": "refresh_token",
            },
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    data = resp.json()
    _token["access_token"] = data["access_token"]
    _token["expires_at"] = time.time() + data.get("expires_in", 3600) - 60
    return _token["access_token"]


@router.get("/status")
def google_status():
    faltando = _falta_escopo()
    return {
        "configured": bool(store.get_secret("google_client_id")),
        "connected": bool(_token.get("access_token") or _token.get("refresh_token")),
        "scopes_faltando": faltando,
        "precisa_reconectar": bool(faltando),
        "aviso": (
            "Este app passou a usar permissões novas (enviar e-mail e calendário). "
            "O acesso que você concedeu antes não as cobre — reconecte o Google "
            "para liberar, senão essas ações falham com 403."
        ) if faltando else None,
    }


def _header(headers: list, name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


@router.get("/gmail/messages")
async def gmail_messages(q: str = "", max_results: int = 10):
    """Lista e-mails JÁ ENRIQUECIDOS: assunto, remetente, data e trecho — não só IDs.

    A API do Gmail devolve só {id, threadId} no list; aqui buscamos o metadata de
    cada mensagem em paralelo pra o resultado ser realmente útil no site.
    """
    token = await _access_token()
    auth = {"Authorization": f"Bearer {token}"}
    max_results = max(1, min(max_results, 25))
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        resp = await client.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            headers=auth, params={"q": q, "maxResults": max_results},
        )
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        ids = [m["id"] for m in resp.json().get("messages", [])]

        async def detail(mid: str) -> dict:
            r = await client.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}",
                headers=auth,
                params=[("format", "metadata"),
                        ("metadataHeaders", "Subject"),
                        ("metadataHeaders", "From"),
                        ("metadataHeaders", "Date")],
            )
            if r.status_code >= 400:
                return {"id": mid, "subject": "(erro ao ler)", "from": "", "date": "", "snippet": ""}
            d = r.json()
            hs = d.get("payload", {}).get("headers", [])
            return {
                "id": mid,
                "subject": _header(hs, "Subject") or "(sem assunto)",
                "from": _header(hs, "From"),
                "date": _header(hs, "Date"),
                "snippet": d.get("snippet", ""),
                "link": f"https://mail.google.com/mail/u/0/#inbox/{mid}",
            }

        messages = await asyncio.gather(*(detail(i) for i in ids)) if ids else []
    return {"messages": messages, "count": len(messages)}


@router.get("/drive/files")
async def drive_files(q: str = "", page_size: int = 20):
    token = await _access_token()
    params = {"pageSize": page_size, "fields": "files(id,name,mimeType,modifiedTime,webViewLink)"}
    if q:
        params["q"] = q
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        resp = await client.get(
            "https://www.googleapis.com/drive/v3/files",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


# =====================================================================
# Enviar e-mail
# =====================================================================
class EnviaEmailIn(BaseModel):
    to: str = Field(min_length=3, max_length=320)
    subject: str = Field(default="", max_length=500)
    body: str = Field(min_length=1, max_length=100_000)


@router.post("/gmail/send")
async def gmail_send(body: EnviaEmailIn):
    """Envia um e-mail em seu nome.

    FORMATO: a API do Gmail não recebe destinatário e corpo como campos. Recebe
    uma mensagem RFC 2822 inteira, codificada em base64 URL-SAFE — sem `+`, sem
    `/` e sem `=` no fim. Base64 comum é recusado, e o erro que volta não diz
    isso com clareza.

    ISTO É IRREVERSÍVEL. Não existe "desenviar". A confirmação de quem manda
    acontece no painel, antes desta chamada — aqui só ficam as travas que não
    dependem de tela: um destinatário por vez e escopo conferido.
    """
    token = await _access_token()

    faltando = _falta_escopo()
    if faltando:
        raise HTTPException(
            status_code=403,
            detail="O acesso concedido ao Google não cobre o envio de e-mail. "
                   "Reconecte em Configurações > Conectores > Google.")

    destino = body.to.strip()
    # Um destinatário por vez, de propósito: aceitar lista aqui deixaria um
    # modelo a um erro de distância de mandar a mesma mensagem pra agenda toda.
    if "," in destino or ";" in destino:
        raise HTTPException(
            status_code=400,
            detail="Um destinatário por vez. Para vários, envie um de cada vez.")
    if "@" not in destino or destino.startswith("@") or destino.endswith("@"):
        raise HTTPException(status_code=400, detail=f"Endereço inválido: {destino!r}")

    msg = EmailMessage()
    msg["To"] = destino
    msg["Subject"] = body.subject or "(sem assunto)"
    msg.set_content(body.body)
    cru = base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip("=")

    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        resp = await client.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {token}"},
            json={"raw": cru},
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])
    d = resp.json()
    return {"ok": True, "id": d.get("id"), "to": destino, "subject": msg["Subject"]}


# =====================================================================
# Calendário
# =====================================================================
FUSO_PADRAO = "America/Sao_Paulo"


@router.get("/calendar/events")
async def calendar_events(days: int = 7, max_results: int = 20):
    """Próximos eventos, do agora até `days` dias à frente.

    `singleEvents=true` + `orderBy=startTime` não é detalhe: sem isso um evento
    que se repete volta como UMA entrada com a regra de recorrência, e "o que eu
    tenho amanhã" passa a não incluir a reunião semanal.
    """
    token = await _access_token()
    days = max(1, min(days, 90))
    agora = datetime.now(timezone.utc)
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        resp = await client.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "timeMin": agora.isoformat().replace("+00:00", "Z"),
                "timeMax": (agora + timedelta(days=days)).isoformat().replace("+00:00", "Z"),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": max(1, min(max_results, 50)),
            },
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])
    itens = resp.json().get("items", [])
    return {"events": [
        {
            "id": e.get("id"),
            "titulo": e.get("summary", "(sem título)"),
            # `date` (dia inteiro) e `dateTime` (com hora) são campos
            # diferentes; usar só um perde metade da agenda.
            "inicio": (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date"),
            "fim": (e.get("end") or {}).get("dateTime") or (e.get("end") or {}).get("date"),
            "dia_inteiro": bool((e.get("start") or {}).get("date")),
            "local": e.get("location", ""),
            "link": e.get("htmlLink", ""),
        } for e in itens], "count": len(itens)}


class EventoIn(BaseModel):
    titulo: str = Field(min_length=1, max_length=300)
    inicio: str = Field(min_length=10, max_length=40)   # ISO 8601
    fim: str | None = None
    descricao: str = ""
    local: str = ""
    fuso: str = FUSO_PADRAO


@router.post("/calendar/events")
async def criar_evento(body: EventoIn):
    """Cria um evento no calendário principal.

    FUSO: se `inicio` vier sem fuso ("2026-08-02T15:00"), o Google usa o
    timeZone informado ao lado. Sem ele, o evento cai no fuso do calendário —
    que pode não ser o seu, e o sintoma é reunião marcada três horas errada.
    """
    token = await _access_token()
    faltando = _falta_escopo()
    if faltando:
        raise HTTPException(
            status_code=403,
            detail="O acesso concedido ao Google não cobre o calendário. "
                   "Reconecte em Configurações > Conectores > Google.")

    # Sem hora de fim, uma hora de duração — é o padrão que qualquer agenda usa,
    # e é melhor que recusar por falta de um campo que ninguém dita em voz alta.
    fim = body.fim
    if not fim:
        try:
            base = datetime.fromisoformat(body.inicio.replace("Z", "+00:00"))
            fim = (base + timedelta(hours=1)).isoformat()
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Não entendi a data de início {body.inicio!r}. "
                       "Use ISO 8601, ex.: 2026-08-02T15:00")

    evento = {
        "summary": body.titulo,
        "start": {"dateTime": body.inicio, "timeZone": body.fuso},
        "end": {"dateTime": fim, "timeZone": body.fuso},
    }
    if body.descricao:
        evento["description"] = body.descricao
    if body.local:
        evento["location"] = body.local

    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        resp = await client.post(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers={"Authorization": f"Bearer {token}"},
            json=evento,
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])
    d = resp.json()
    return {"ok": True, "id": d.get("id"), "titulo": d.get("summary"),
            "inicio": (d.get("start") or {}).get("dateTime"), "link": d.get("htmlLink")}
