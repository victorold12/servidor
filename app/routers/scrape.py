"""/api/scrape e /api/search — destravam o que o navegador não faz por CORS."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import image_search, scrape_url, web_search

router = APIRouter()


class ScrapeIn(BaseModel):
    url: str


class SearchIn(BaseModel):
    q: str
    max: int = 6


class ImagesIn(BaseModel):
    q: str
    max: int = 10


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


@router.post("/images")
async def images(body: ImagesIn):
    """Busca imagens sobre o tema (DuckDuckGo). Retorna thumbnail, imagem e fonte."""
    try:
        return {"results": await image_search(body.q, body.max)}
    except Exception as exc:  # noqa: BLE001
        return {"results": [], "error": str(exc)}


@router.get("/skillsh")
async def skillsh_catalog():
    """Catálogo do skills.sh (biblioteca de skills de agente).

    Best-effort: tenta um endpoint JSON; se não houver, raspa os links da home.
    Retorna [{name, url}] apontando pra página de cada skill no skills.sh."""
    import httpx as _httpx
    from bs4 import BeautifulSoup as _BS

    from ..config import settings as _st
    headers = {"User-Agent": "Mozilla/5.0 (compatible; VTzBot/1.0)"}
    async with _httpx.AsyncClient(timeout=_st.request_timeout, headers=headers, follow_redirects=True) as client:
        # 1) tenta API JSON (se o site expuser)
        for api in ("https://skills.sh/api/skills", "https://www.skills.sh/api/skills"):
            try:
                r = await client.get(api)
                if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                    data = r.json()
                    items = data if isinstance(data, list) else data.get("skills") or data.get("items") or []
                    out = []
                    for it in items[:100]:
                        name = it.get("name") or it.get("slug") or ""
                        url = it.get("url") or ("https://skills.sh/" + it.get("slug", ""))
                        if name:
                            out.append({"name": name, "url": url, "desc": it.get("description", "")})
                    if out:
                        return {"skills": out, "source": "api"}
            except Exception:  # noqa: BLE001
                pass
        # 2) raspa a home
        try:
            r = await client.get("https://skills.sh/")
            r.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"skills.sh inacessível: {exc}")
    soup = _BS(r.text, "html.parser")
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = " ".join(a.get_text(" ").split())
        if not text or len(text) < 3:
            continue
        if href.startswith("/") and href.count("/") >= 2 and not href.startswith(("/api", "/_")):
            full = "https://skills.sh" + href
            if full not in seen:
                seen.add(full)
                out.append({"name": text[:80], "url": full, "desc": ""})
        if len(out) >= 60:
            break
    return {"skills": out, "source": "scrape"}
