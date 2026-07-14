from fastapi import APIRouter

from ..config import settings

router = APIRouter()


@router.get("/health")
def health():
    return {
        "ok": True,
        "service": settings.site_title,
        "openrouter_key_from_env": bool(settings.openrouter_api_key),
        "notion_configured": bool(settings.notion_token),
    }
