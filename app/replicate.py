"""Ponte com a API de geração do Replicate.

A chave do Replicate NUNCA é gravada no servidor: o site envia a chave do usuário
no header (X-Replicate-Key ou Authorization). Só se nada vier, cai no valor do .env.
Assim mantemos o princípio do projeto: a chave vive no navegador do usuário.

Replicate agrega: Kling AI, Runway, Luma Dream Machine, Veo, Seedance, Hailuo, Wan, etc.
"""
import httpx

from .config import settings


def resolve_key(header_value: str | None) -> str:
    key = (header_value or "").strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key or settings.replicate_api_key


async def predict(model: str, input_data: dict, key: str | None = None) -> dict:
    """Inicia uma prediction (async task) no Replicate.

    Retorna: {"id": "uuid...", "status": "starting", "model": "...", "input": {...}, ...}
    """
    if not key:
        raise ValueError("Sem chave do Replicate (envie no header X-Replicate-Key ou configure REPLICATE_API_KEY).")

    payload = {"version": None, "model": model, "input": input_data, "webhook_completed": None}
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",  # retorna logo a prediction criada
    }
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        resp = await client.post(
            "https://api.replicate.com/v1/predictions", json=payload, headers=headers
        )
        resp.raise_for_status()
        return resp.json()


async def get_prediction(prediction_id: str, key: str | None = None) -> dict:
    """Busca status/resultado de uma prediction."""
    if not key:
        raise ValueError("Sem chave do Replicate.")

    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        resp = await client.get(f"https://api.replicate.com/v1/predictions/{prediction_id}", headers=headers)
        resp.raise_for_status()
        return resp.json()


async def cancel_prediction(prediction_id: str, key: str | None = None) -> dict:
    """Cancela uma prediction em progresso."""
    if not key:
        raise ValueError("Sem chave do Replicate.")

    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        resp = await client.post(
            f"https://api.replicate.com/v1/predictions/{prediction_id}/cancel", headers=headers
        )
        resp.raise_for_status()
        return resp.json()
