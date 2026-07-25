"""Ponte com a API de chat do OpenRouter.

A chave do OpenRouter NUNCA é gravada no servidor: o site envia a chave do usuário
no header (X-OR-Key ou Authorization). Só se nada vier, cai no valor do .env.
Assim mantemos o princípio do projeto: a chave vive no navegador do usuário.

Duas formas de chamar: `chat` (espera a resposta inteira) e `chat_stream`
(devolve os pedaços conforme chegam). O JARVIS usa o streaming pro texto
aparecer aos poucos no painel; o resto do backend segue usando `chat`.
"""
import json

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


async def chat_stream(messages: list[dict], key: str, model: str | None = None,
                      tools: list | None = None):
    """Versão streaming de `chat`. Gera dicionários conforme o modelo responde:

      {"type": "token", "text": "..."}   pedaço de texto
      {"type": "tool_calls", "calls": [...]}  o modelo pediu ferramentas (no fim)
      {"type": "usage", ...}             contagem real de tokens, quando vier
      {"type": "finish", "reason": "..."}

    As chamadas de ferramenta chegam fatiadas no stream (o `arguments` vem letra
    por letra), então acumulamos por índice e só emitimos quando fecha.
    """
    if not key:
        raise ValueError("Sem chave do OpenRouter (envie no header X-OR-Key ou configure OPENROUTER_API_KEY).")
    payload: dict = {
        "model": model or settings.default_model,
        "messages": messages,
        "stream": True,
        # pede a contagem de tokens no último pedaço, pra não estimar custo no cliente
        "stream_options": {"include_usage": True},
    }
    if tools:
        payload["tools"] = tools
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Title": settings.site_title,
    }

    partial: dict[int, dict] = {}   # índice -> chamada de ferramenta em construção
    finish = None

    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        async with client.stream(
            "POST", f"{settings.openrouter_base}/chat/completions",
            json=payload, headers=headers,
        ) as resp:
            if resp.status_code >= 400:
                detail = (await resp.aread()).decode("utf-8", "replace")[:400]
                raise httpx.HTTPStatusError(
                    f"OpenRouter {resp.status_code}: {detail}",
                    request=resp.request, response=resp,
                )
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue

                if chunk.get("usage"):
                    yield {"type": "usage", **chunk["usage"]}

                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    text = delta.get("content")
                    if text:
                        yield {"type": "token", "text": text}
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        slot = partial.setdefault(
                            idx, {"id": None, "function": {"name": "", "arguments": ""}})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["function"]["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["function"]["arguments"] += fn["arguments"]
                    if choice.get("finish_reason"):
                        finish = choice["finish_reason"]

    if partial:
        yield {"type": "tool_calls",
               "calls": [partial[i] for i in sorted(partial)]}
    yield {"type": "finish", "reason": finish or "stop"}


def content_of(data: dict) -> str:
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""
