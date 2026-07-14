"""/api/connectors/* — esqueleto dos conectores externos.

Cada conector precisa da chave DELE, que só VOCÊ consegue gerar:
- Notion: crie uma integração em https://www.notion.so/my-integrations,
  copie o "Internal Integration Token" para NOTION_TOKEN no .env, e compartilhe
  as páginas/bancos com a integração.

Figma, Google/Office etc. seguem o mesmo padrão: registrar um app OAuth no
provedor, guardar o token e chamar a API deles. Deixei o Notion pronto como
modelo funcional — replique a estrutura para os outros.
"""
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import settings

router = APIRouter()


class NotionSearchIn(BaseModel):
    query: str = ""


@router.get("/status")
def status():
    return {
        "notion": bool(settings.notion_token),
        # adicione outros conectores aqui conforme configurar
    }


@router.post("/notion/search")
async def notion_search(body: NotionSearchIn):
    if not settings.notion_token:
        raise HTTPException(
            status_code=400,
            detail="NOTION_TOKEN não configurado. Crie a integração em "
                   "notion.so/my-integrations, cole o token no .env e compartilhe "
                   "as páginas com a integração.",
        )
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        resp = await client.post(
            "https://api.notion.com/v1/search",
            headers={
                "Authorization": f"Bearer {settings.notion_token}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            },
            json={"query": body.query} if body.query else {},
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()
