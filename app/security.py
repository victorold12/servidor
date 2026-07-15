"""Autenticação por token + guarda de SSRF + rate limit simples.

Protege o backend quando publicado na internet: sem isso, qualquer um que
souber a URL pode usar (e gastar) os endpoints que fazem chamadas externas.
"""
import ipaddress
import socket
import time
from collections import defaultdict
from urllib.parse import urlparse

from fastapi import Header, HTTPException, Request

from .config import settings


# ---------------- Autenticação por token ----------------
def require_token(x_backend_token: str | None = Header(default=None)):
    """Se BACKEND_TOKEN estiver configurado (env var no Render), exige o header
    X-Backend-Token igual. Sem BACKEND_TOKEN configurado, fica aberto — é o modo
    de desenvolvimento local, onde só você tem acesso à máquina de qualquer jeito."""
    if not settings.backend_token:
        return
    if not x_backend_token or x_backend_token != settings.backend_token:
        raise HTTPException(status_code=401, detail="Token do backend ausente ou inválido.")


# ---------------- Rate limit (janela fixa, em memória, por IP) ----------------
_hits: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT = 30      # requisições
RATE_WINDOW = 300.0  # por 5 minutos, por IP


def rate_limit(request: Request):
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    hits = _hits[ip]
    while hits and hits[0] < now - RATE_WINDOW:
        hits.pop(0)
    if len(hits) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Muitas requisições — aguarde alguns minutos.")
    hits.append(now)


# ---------------- Guarda de SSRF ----------------
def assert_public_url(url: str):
    """Bloqueia scrape/fetch pra IPs internos (localhost, rede privada, metadata
    da cloud). Sem isso, /api/scrape vira um proxy pra rede interna do servidor."""
    parsed = urlparse(url if "://" in url else "https://" + url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Só URLs http/https são permitidas.")
    host = parsed.hostname
    if not host:
        raise HTTPException(status_code=400, detail="URL inválida.")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise HTTPException(status_code=400, detail=f"Não consegui resolver o host: {host}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise HTTPException(status_code=400, detail="URL aponta pra rede interna — bloqueado por segurança.")
