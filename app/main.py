"""VTz LLM Backend — API que o site (index.html) chama por HTTP.

Sobe com:  uvicorn app.main:app --reload
Docs interativas em /docs
"""
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import agent, autonomous, connectors, google, health, mcp_client, research, scrape
from .security import rate_limit, require_token

app = FastAPI(title=settings.site_title, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# /api/health fica sem trava — é só um status, sem dado sensível, e é usado
# pela auto-detecção do site. Todo o resto exige token (se BACKEND_TOKEN
# estiver configurado) e tem limite de requisições por IP.
protected = [Depends(require_token), Depends(rate_limit)]

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(scrape.router, prefix="/api", tags=["scrape"], dependencies=protected)
app.include_router(research.router, prefix="/api", tags=["research"], dependencies=protected)
app.include_router(agent.router, prefix="/api", tags=["agent"], dependencies=protected)
app.include_router(autonomous.router, prefix="/api", tags=["autonomous"], dependencies=protected)
app.include_router(connectors.router, prefix="/api/connectors", tags=["connectors"], dependencies=protected)
app.include_router(google.router, prefix="/api/connectors/google", tags=["google"], dependencies=protected)
app.include_router(mcp_client.router, prefix="/api/mcp", tags=["mcp"], dependencies=protected)


@app.get("/")
def root():
    return {"name": settings.site_title, "docs": "/docs", "health": "/api/health"}
