"""Serviços de rede reutilizados pelos routers: scraping e busca web sem chave.

- scrape_url: baixa uma página no servidor (sem o bloqueio de CORS do navegador)
  e extrai título, descrição, imagem (og:image) e texto. É isto que destrava as
  "imagens da fonte" na busca estilo ChatGPT.
- web_search: busca no DuckDuckGo HTML (sem API key). É honesto e funciona, mas é
  scraping — pode quebrar se o DuckDuckGo mudar o HTML. Troque por uma API paga
  (Brave, Serper, Tavily) quando quiser robustez.
"""
from urllib.parse import urlparse, parse_qs, unquote

import httpx
from bs4 import BeautifulSoup

from .config import settings

_UA = "Mozilla/5.0 (compatible; VTzBot/1.0)"


async def scrape_url(url: str) -> dict:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    async with httpx.AsyncClient(
        timeout=settings.request_timeout, follow_redirects=True, headers={"User-Agent": _UA}
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        html = resp.text
        final_url = str(resp.url)

    soup = BeautifulSoup(html, "html.parser")

    def meta(key: str):
        el = soup.find("meta", property=key) or soup.find("meta", attrs={"name": key})
        return el.get("content").strip() if el and el.get("content") else None

    title = meta("og:title")
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ").split())[:5000]

    return {
        "url": final_url,
        "title": title,
        "description": meta("og:description") or meta("description"),
        "image": meta("og:image"),
        "site": meta("og:site_name") or urlparse(final_url).netloc,
        "text": text,
    }


async def web_search(query: str, max_results: int = 6) -> list[dict]:
    if not query.strip():
        return []
    async with httpx.AsyncClient(
        timeout=settings.request_timeout, headers={"User-Agent": _UA}
    ) as client:
        resp = await client.post("https://html.duckduckgo.com/html/", data={"q": query})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

    results: list[dict] = []
    for node in soup.select(".result")[:max_results]:
        link = node.select_one(".result__a")
        if not link:
            continue
        href = link.get("href", "")
        if "uddg=" in href:  # DuckDuckGo embrulha o link real num redirect
            wrapped = parse_qs(urlparse(href).query).get("uddg", [href])
            href = unquote(wrapped[0])
        snippet = node.select_one(".result__snippet")
        results.append(
            {
                "title": link.get_text(" ").strip(),
                "url": href,
                "snippet": snippet.get_text(" ").strip() if snippet else "",
            }
        )
    return results
