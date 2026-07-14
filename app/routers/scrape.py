"""/api/scrape e /api/search — destravam o que o navegador não faz por CORS."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import scrape_url, web_search

router = APIRouter()


class ScrapeIn(BaseModel):
    url: str


class SearchIn(BaseModel):
    q: str
    max: int = 6


@router.post("/scrape")
async def scrape(body: ScrapeIn):
    """Baixa uma página no servidor e devolve título, descrição, og:image e texto.
    É isto que permite mostrar a imagem/preview da fonte na busca (o navegador
    não consegue por CORS)."""
    try:
        return await scrape_url(body.url)
    except Exception as exc:  # noqa: BLE001 — devolve erro legível pro site
        raise HTTPException(status_code=400, detail=f"Falha ao ler a página: {exc}")


@router.post("/search")
async def search(body: SearchIn):
    """Busca web sem chave (DuckDuckGo). Retorna título, url e trecho."""
    try:
        return {"results": await web_search(body.q, body.max)}
    except Exception as exc:  # noqa: BLE001
        return {"results": [], "error": str(exc)}
