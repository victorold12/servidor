"""/api/connectors/* — conectores por token (grátis).

Cada conector precisa da chave DELE, gerada por VOCÊ (nenhuma é paga):
- Notion:  https://www.notion.so/my-integrations  -> NOTION_TOKEN
- Figma:   https://www.figma.com/developers/api#access-tokens -> FIGMA_TOKEN
  (Configurações da conta > Personal access tokens)

Google (Gmail/Drive) usa OAuth e fica no router google.py.
"""
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import settings
from .. import store

router = APIRouter()


@router.get("/status")
def status():
    st = store.status()
    return {
        "notion": st.get("notion_token", False),
        "figma": st.get("figma_token", False),
        "google": bool(store.get_secret("google_client_id") and store.get_secret("google_client_secret")),
    }


class ConfigIn(BaseModel):
    notion_token: str | None = None
    figma_token: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None


@router.get("/config")
def get_config():
    """Quais chaves estão setadas (nunca devolve o valor em si)."""
    return store.status()


@router.post("/config")
def set_config(body: ConfigIn):
    """Salva as chaves enviadas pelo site. "" limpa; ausente mantém."""
    store.set_secrets(body.model_dump(exclude_none=True))
    return {"ok": True, **store.status()}


# ---------------- Notion ----------------
class NotionSearchIn(BaseModel):
    query: str = ""


@router.post("/notion/search")
async def notion_search(body: NotionSearchIn):
    token = store.get_secret("notion_token")
    if not token:
        raise HTTPException(
            status_code=400,
            detail="Token do Notion não configurado. Cole-o na aba Conectores do site "
                   "(crie a integração em notion.so/my-integrations e compartilhe as páginas com ela).",
        )
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        resp = await client.post(
            "https://api.notion.com/v1/search",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            },
            json={"query": body.query} if body.query else {},
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


# ---------------- Figma ----------------
def _figma_headers():
    token = store.get_secret("figma_token")
    if not token:
        raise HTTPException(
            status_code=400,
            detail="Token do Figma não configurado. Cole-o na aba Conectores do site "
                   "(Figma > Settings > Personal access tokens).",
        )
    return {"X-Figma-Token": token}


@router.get("/figma/me")
async def figma_me():
    """Dados da conta — serve pra testar se o token funciona."""
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        resp = await client.get("https://api.figma.com/v1/me", headers=_figma_headers())
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


@router.get("/figma/file/{file_key}")
async def figma_file(file_key: str):
    """Estrutura (nós, páginas, componentes) de um arquivo do Figma pela sua key
    (o trecho da URL: figma.com/file/<file_key>/...)."""
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        resp = await client.get(
            f"https://api.figma.com/v1/files/{file_key}", headers=_figma_headers()
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


@router.get("/figma/file/{file_key}/images")
async def figma_images(file_key: str, ids: str, format: str = "png"):
    """Renderiza nós do arquivo como imagem. `ids` = ids de nós separados por vírgula."""
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        resp = await client.get(
            f"https://api.figma.com/v1/images/{file_key}",
            headers=_figma_headers(),
            params={"ids": ids, "format": format},
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()
