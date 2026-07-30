"""/api/models — catálogo de modelos do OpenRouter, com preço.

Por que existe: o painel precisa da lista pra montar o seletor (nome, provedor,
preço por 1M tokens, contexto). Sem esta rota, cada frente — site, extensão,
JARVIS, Electron — teria que falar direto com o OpenRouter, o que quebra o
princípio da Seção 7 do prompt mestre: o backend é a fonte única.

Cache em dicionário na memória do processo, como decidido na Seção 2 (sem Redis
para um usuário). O catálogo muda devagar; meia hora de validade evita repetir a
chamada a cada abertura do seletor.

A resposta diz de onde veio (`source`) e quando foi buscada. Se o OpenRouter
estiver fora do ar e não houver nada em cache, devolve 503 com o motivo — não
inventa lista nem devolve vazio como se fosse a verdade.
"""
import time

import httpx
from fastapi import APIRouter, Header, HTTPException

from ..config import settings
from ..openrouter import resolve_key

router = APIRouter()

_TTL = 1800.0          # 30 min
_cache: dict = {"at": 0.0, "models": None}


def _slim(m: dict) -> dict:
    """Guarda só o que o seletor usa. O payload do OpenRouter é bem maior."""
    return {
        "id": m.get("id"),
        "name": m.get("name") or m.get("id"),
        "pricing": {
            "prompt": (m.get("pricing") or {}).get("prompt", "0"),
            "completion": (m.get("pricing") or {}).get("completion", "0"),
        },
        "context_length": m.get("context_length"),
        "architecture": m.get("architecture"),
        "created": m.get("created"),
    }


async def fetch_catalog(key: str = "", refresh: bool = False) -> tuple[list[dict], str]:
    """Devolve (modelos, origem). Reaproveitado pela rota e pelo roteador de
    modelos — os dois precisam da mesma lista, e nenhum deve manter a sua.

    Origem é uma de: "cache", "openrouter", "cache_expirado". Levanta se não
    houver nem rede nem cache: sem lista, quem chamou decide o que fazer, mas
    ninguém segue com lista vazia achando que é a verdade.
    """
    agora = time.time()
    if not refresh and _cache["models"] and agora - _cache["at"] < _TTL:
        return _cache["models"], "cache"

    headers = {"X-Title": settings.site_title}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            resp = await client.get(f"{settings.openrouter_base}/models", headers=headers)
            resp.raise_for_status()
            bruto = resp.json().get("data") or []
    except Exception as exc:  # noqa: BLE001 — rede/upstream fora do nosso controle
        if _cache["models"]:
            return _cache["models"], "cache_expirado"
        raise RuntimeError(f"OpenRouter inacessível: {exc}") from exc

    modelos = [_slim(m) for m in bruto if m.get("id")]
    if not modelos:
        if _cache["models"]:
            return _cache["models"], "cache_expirado"
        raise RuntimeError("OpenRouter devolveu catálogo vazio.")

    _cache["models"] = modelos
    _cache["at"] = agora
    return modelos, "openrouter"


@router.get("/models")
async def list_models(
    refresh: bool = False,
    x_or_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    # a chave é opcional aqui: /models é público no OpenRouter. Se o usuário
    # mandou a dele, usamos — alguns planos veem modelos a mais.
    key = resolve_key(x_or_key or authorization)
    try:
        modelos, origem = await fetch_catalog(key, refresh)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Não foi possível obter o catálogo do OpenRouter: {exc}",
        ) from exc

    corpo = {
        "source": origem,
        "fetched_at": _cache["at"],
        "count": len(modelos),
        "data": modelos,
    }
    if origem == "cache_expirado":
        corpo["warning"] = ("OpenRouter inacessível agora. Lista pode estar desatualizada.")
    return corpo
