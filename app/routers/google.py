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
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from ..config import settings
from .. import store

router = APIRouter()

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "openid", "email",
]

# token em memória (single-user scaffold): {access_token, refresh_token, expires_at}
_token: dict = {}


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
    return {"configured": bool(store.get_secret("google_client_id")), "connected": bool(_token.get("access_token"))}


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
