"""/api/video/* — Geração de vídeo via Replicate.

Replicate agrega os principais modelos: Kling AI, Runway Gen-3, Luma Dream Machine,
Google Veo, Seedance, Hailuo, Wan, e upscalers. Uma chave única (REPLICATE_API_KEY)
acessa todos — sem criar conta em cada provedor.

Fluxo:
1. POST /api/video/generate → inicia async job, retorna {id, status}
2. GET /api/video/prediction/{id} → pooling do status
3. Quando status="succeeded" → output (URL do vídeo, etc.)
"""
import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from ..config import settings
from ..replicate import resolve_key, predict, get_prediction, cancel_prediction

router = APIRouter()


# Catálogo de modelos disponíveis no Replicate (mais populares)
MODELS = {
    "kling-v1": {
        "id": "kling-ai/kling-v1",
        "name": "Kling AI v1.0",
        "type": "text-to-video",
        "params": ["prompt", "duration"],
        "max_duration": 10,
    },
    "kling-v2": {
        "id": "kling-ai/kling-v2",
        "name": "Kling AI v2.0",
        "type": "text-to-video",
        "params": ["prompt", "duration"],
        "max_duration": 10,
    },
    "kling-v3": {
        "id": "kling-ai/kling-v3",
        "name": "Kling AI v3.0 (recomendado)",
        "type": "text-to-video",
        "params": ["prompt", "duration"],
        "max_duration": 10,
    },
    "runway-gen3": {
        "id": "runwayml/gen-3-5-motion",
        "name": "Runway Gen-3.5 Motion",
        "type": "text-to-video",
        "params": ["prompt", "duration"],
        "max_duration": 25,
    },
    "luma-dream": {
        "id": "luma-ai/photorealistic-world-model",
        "name": "Luma Dream Machine",
        "type": "text-to-video",
        "params": ["prompt"],
        "max_duration": 5,
    },
    "veo-2": {
        "id": "google-deepmind/veo-2",
        "name": "Google Veo 2.0",
        "type": "text-to-video",
        "params": ["prompt", "duration"],
        "max_duration": 6,
    },
    "seedance": {
        "id": "seedance/i2v-refiner",
        "name": "Seedance (Imagem → Vídeo)",
        "type": "image-to-video",
        "params": ["image", "prompt"],
        "max_duration": 5,
    },
    "hailuo": {
        "id": "hailuo/video-generation",
        "name": "Hailuo Video Generation",
        "type": "text-to-video",
        "params": ["prompt", "duration"],
        "max_duration": 10,
    },
}


class GenerateIn(BaseModel):
    """Solicita geração de vídeo."""
    model: str  # chave em MODELS (ex: "kling-v3", "runway-gen3")
    prompt: str  # descrição do vídeo desejado
    duration: int | None = None  # em segundos (se aplicável)
    image_url: str | None = None  # pra image-to-video (Seedance)


@router.get("/status")
def video_status():
    """Verifica se Replicate está configurado."""
    return {
        "configured": bool(settings.replicate_api_key),
        "models_available": len(MODELS),
    }


@router.get("/models")
def list_models():
    """Lista todos os modelos de vídeo disponíveis."""
    return {
        "models": [
            {
                "id": mid,
                "name": m["name"],
                "type": m["type"],
                "max_duration": m.get("max_duration"),
            }
            for mid, m in MODELS.items()
        ]
    }


@router.post("/generate")
async def generate(body: GenerateIn, x_replicate_key: str | None = Header(default=None)):
    """Inicia geração de vídeo. Retorna prediction ID pra polling."""
    key = resolve_key(x_replicate_key)
    if not key:
        raise HTTPException(
            status_code=400,
            detail="Chave do Replicate não configurada. Cole-a na aba Conectores do site "
                   "(crie conta grátis em replicate.com).",
        )

    if body.model not in MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Modelo '{body.model}' desconhecido. Veja /api/video/models.",
        )

    model_info = MODELS[body.model]
    input_data = {"prompt": body.prompt}

    # Validar duration se aplicável
    if "duration" in model_info["params"]:
        duration = body.duration or 5
        if duration > model_info["max_duration"]:
            raise HTTPException(
                status_code=400,
                detail=f"{model_info['name']} suporta até {model_info['max_duration']}s, não {duration}s.",
            )
        input_data["duration"] = duration

    # Image URL pra image-to-video
    if model_info["type"] == "image-to-video" and body.image_url:
        input_data["image"] = body.image_url

    try:
        result = await predict(model_info["id"], input_data, key=key)
        return {
            "id": result.get("id"),
            "status": result.get("status"),
            "model": body.model,
            "model_name": model_info["name"],
            "created_at": result.get("created_at"),
        }
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Replicate error: {exc.response.text[:200]}",
        )


@router.get("/prediction/{prediction_id}")
async def get_status(prediction_id: str, x_replicate_key: str | None = Header(default=None)):
    """Polling: status de uma prediction."""
    key = resolve_key(x_replicate_key)
    if not key:
        raise HTTPException(status_code=400, detail="Chave do Replicate não configurada.")

    try:
        data = await get_prediction(prediction_id, key=key)
        return {
            "id": data.get("id"),
            "status": data.get("status"),
            "output": data.get("output"),  # URL do vídeo quando pronto
            "error": data.get("error"),
            "created_at": data.get("created_at"),
            "completed_at": data.get("completed_at"),
            "metrics": data.get("metrics"),  # tempos, etc.
        }
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Replicate error: {exc.response.text[:200]}",
        )


@router.post("/prediction/{prediction_id}/cancel")
async def cancel(prediction_id: str, x_replicate_key: str | None = Header(default=None)):
    """Cancela um vídeo em geração."""
    key = resolve_key(x_replicate_key)
    if not key:
        raise HTTPException(status_code=400, detail="Chave do Replicate não configurada.")

    try:
        data = await cancel_prediction(prediction_id, key=key)
        return {"id": data.get("id"), "status": data.get("status")}
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Replicate error: {exc.response.text[:200]}",
        )
