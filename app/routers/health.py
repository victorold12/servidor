from fastapi import APIRouter

from .. import store
from ..config import settings

router = APIRouter()


@router.get("/health")
def health():
    return {
        "ok": True,
        "service": settings.site_title,
        "openrouter_key_from_env": bool(settings.openrouter_api_key),
        "notion_configured": bool(store.get_secret("notion_token")),
        "auth_enabled": bool(settings.backend_token),
    }
