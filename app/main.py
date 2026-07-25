"""VTz LLM Backend — API que o site (index.html) chama por HTTP.

Sobe com:  uvicorn app.main:app --reload
Docs interativas em /docs
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import autobackup, db
from .config import settings
from .routers import agent, agents_hub, analytics, autonomous, backup, catalog, connectors, conversations, google, health, mcp_client, memory, messaging, orchestrate, pairing, research, scrape, video, voice
from .security import rate_limit, require_token

logger = logging.getLogger("vtz_backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    # Render seta a env var RENDER=true automaticamente em todo deploy — é o
    # sinal mais confiável de "isto não é a máquina local do dev".
    if os.environ.get("RENDER") and not settings.backend_token:
        logger.warning(
            "BACKEND_TOKEN não configurado em produção (Render) — o backend "
            "está aberto para qualquer um na internet usar. Configure "
            "BACKEND_TOKEN em Environment no painel do Render."
        )
    # Backup automático: tarefa de fundo, e só existe se BACKUP_EVERY_HOURS > 0.
    tarefa = None
    if settings.backup_every_hours > 0:
        tarefa = asyncio.create_task(autobackup.loop_agendado())
        logger.info("backup automático a cada %sh em %s",
                    settings.backup_every_hours, autobackup.diretorio())
    try:
        yield
    finally:
        if tarefa is not None:
            tarefa.cancel()


app = FastAPI(title=settings.site_title, version="0.1.0", lifespan=lifespan)

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
app.include_router(orchestrate.router, prefix="/api", tags=["orchestrate"], dependencies=protected)
app.include_router(connectors.router, prefix="/api/connectors", tags=["connectors"], dependencies=protected)
app.include_router(google.router, prefix="/api/connectors/google", tags=["google"], dependencies=protected)
app.include_router(video.router, prefix="/api/video", tags=["video"], dependencies=protected)
app.include_router(mcp_client.router, prefix="/api/mcp", tags=["mcp"], dependencies=protected)
app.include_router(memory.router, prefix="/api", tags=["memory"], dependencies=protected)
app.include_router(catalog.router, prefix="/api", tags=["catalog"], dependencies=protected)
app.include_router(analytics.router, prefix="/api", tags=["analytics"], dependencies=protected)
app.include_router(backup.router, prefix="/api", tags=["backup"], dependencies=protected)
app.include_router(conversations.router, prefix="/api", tags=["conversations"], dependencies=protected)
app.include_router(voice.router, prefix="/api", tags=["voice"], dependencies=protected)
# Webhook é chamado por Discord/Telegram, que não têm o token de sessão. A trava
# aqui é outra: segredo no caminho da URL + allowlist de quem pode mandar comando
# (ver routers/messaging.py). Rate limit continua valendo.
app.include_router(messaging.router, prefix="/api", tags=["messaging"],
                   dependencies=[Depends(rate_limit)])

# Pareamento do Agente Local: NÃO leva o `protected` genérico — /pair/start e
# /pair/poll são chamados sem token (o agente ainda não tem nenhum); cada rota
# do módulo declara sua própria auth (ver app/routers/pairing.py).
app.include_router(pairing.router, prefix="/api", tags=["pairing"])

# Hub WebSocket do Agente Local + gestão. Sem prefix aqui de propósito: o WS
# fica em /ws/agent (Seção 12 do esquema — não /api/ws/agent) autenticado pelo
# token do agente (Bearer), não pelo BACKEND_TOKEN; as rotas HTTP de gestão já
# levam "/api" no próprio path e exigem sessão individualmente (ver
# app/routers/agents_hub.py) — por isso também fora do `protected` genérico.
app.include_router(agents_hub.router, tags=["agents"])


@app.get("/")
def root():
    return {"name": settings.site_title, "docs": "/docs", "health": "/api/health"}
