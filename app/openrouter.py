"""Ponte com a API de chat do OpenRouter.

A chave do OpenRouter NUNCA é gravada no servidor: o site envia a chave do usuário
no header (X-OR-Key ou Authorization). Só se nada vier, cai no valor do .env.
Assim mantemos o princípio do projeto: a chave vive no navegador do usuário.
"""
import httpx

from .config import settings


def resolve_key(header_value: str | None) -> str:
    key = (header_value or "").strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key or settings.openrouter_api_key


async def chat(messages: list[dict], key: str, model: str | None = None,
               tools: list | None = None, plugins: list | None = None) -> dict:
    if not key:
        raise ValueError("Sem chave do OpenRouter (envie no header X-OR-Key ou configure OPENROUTER_API_KEY).")
    payload: dict = {"model": model or settings.default_model, "messages": messages}
    if tools:
        payload["tools"] = tools
    if plugins:
        payload["plugins"] = plugins
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Title": settings.site_title,
    }
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        resp = await client.post(
            f"{settings.openrouter_base}/chat/completions", json=payload, headers=headers
        )
        resp.raise_for_status()
        return resp.json()


def content_of(data: dict) -> str:
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""
