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


@router.get("/models")
async def list_models(
    refresh: bool = False,
    x_or_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    agora = time.time()
    if not refresh and _cache["models"] and agora - _cache["at"] < _TTL:
        return {
            "source": "cache",
            "fetched_at": _cache["at"],
            "count": len(_cache["models"]),
            "data": _cache["models"],
        }

    # a chave é opcional aqui: /models é público no OpenRouter. Se o usuário
    # mandou a dele, usamos — alguns planos veem modelos a mais.
    key = resolve_key(x_or_key or authorization)
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
            # cache velho é melhor que nada, mas o cliente precisa saber que é velho
            return {
                "source": "cache_expirado",
                "fetched_at": _cache["at"],
                "count": len(_cache["models"]),
                "warning": f"OpenRouter inacessível agora ({exc}). Lista pode estar desatualizada.",
                "data": _cache["models"],
            }
        raise HTTPException(
            status_code=503,
            detail=f"Não foi possível obter o catálogo do OpenRouter: {exc}",
        ) from exc

    modelos = [_slim(m) for m in bruto if m.get("id")]
    if not modelos:
        raise HTTPException(status_code=503, detail="OpenRouter devolveu catálogo vazio.")

    _cache["models"] = modelos
    _cache["at"] = agora
    return {"source": "openrouter", "fetched_at": agora, "count": len(modelos), "data": modelos}
