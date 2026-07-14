"""VTz LLM Backend — API que o site (index.html) chama por HTTP.

Sobe com:  uvicorn app.main:app --reload
Docs interativas em /docs
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import agent, connectors, google, health, mcp_client, research, scrape

app = FastAPI(title=settings.site_title, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(scrape.router, prefix="/api", tags=["scrape"])
app.include_router(research.router, prefix="/api", tags=["research"])
app.include_router(agent.router, prefix="/api", tags=["agent"])
app.include_router(connectors.router, prefix="/api/connectors", tags=["connectors"])
app.include_router(google.router, prefix="/api/connectors/google", tags=["google"])
app.include_router(mcp_client.router, prefix="/api/mcp", tags=["mcp"])


@app.get("/")
def root():
    return {"name": settings.site_title, "docs": "/docs", "health": "/api/health"}
