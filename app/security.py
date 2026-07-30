"""Autenticação por token + guarda de SSRF + rate limit simples.

Protege o backend quando publicado na internet: sem isso, qualquer um que
souber a URL pode usar (e gastar) os endpoints que fazem chamadas externas.
"""
import hashlib
import ipaddress
import secrets
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
#
# Pra que serve: o backend pode ficar público (Render), e quem protege é o
# BACKEND_TOKEN. O limite aqui é a segunda linha — segura abuso se o token
# vazar ou não estiver configurado, e segura um laço maluco do próprio app.
#
# Por que o padrão é generoso: isto é single-user, e UMA interação do painel já
# faz várias chamadas (catálogo, agente, extração de fato, camada diária, busca).
# Com o antigo 30/5min (6 por minuto) o uso normal batia no teto — a suíte de
# testes batia sozinha. 600/5min ainda é um teto real contra abuso e é invisível
# pra quem está só usando.
#
# Configurável no .env: RATE_LIMIT e RATE_WINDOW.
_hits: dict[str, list[float]] = defaultdict(list)


def rate_limit(request: Request):
    ip = request.client.host if request.client else "unknown"
    limite = max(1, int(settings.rate_limit))
    janela = max(1.0, float(settings.rate_window))
    now = time.time()
    hits = _hits[ip]
    while hits and hits[0] < now - janela:
        hits.pop(0)
    if len(hits) >= limite:
        raise HTTPException(
            status_code=429,
            detail=(f"Muitas requisições ({limite} em {int(janela)}s). "
                    f"Aguarde, ou suba RATE_LIMIT no .env."))
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


# ---------------- Pareamento do Agente Local (docs/SEGURANCA-AGENTE-LOCAL.md) ----------------
# Alfabeto sem caracteres ambíguos (sem 0/O, 1/I/L) — Seção 3: 8 chars ≈ 40 bits.
_USER_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_user_code(length: int = 8) -> str:
    """Código curto que a pessoa digita no site pra reivindicar o pareamento."""
    return "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(length))


def format_user_code(code: str) -> str:
    """'WXYZ2345' -> 'WXYZ-2345', só pra exibição."""
    return f"{code[:4]}-{code[4:]}" if len(code) == 8 else code


def normalize_user_code(code: str) -> str:
    """Remove espaço/hífen e uppercase, pra comparar o que a pessoa digitou."""
    return code.strip().upper().replace("-", "").replace(" ", "")


def generate_device_code() -> str:
    """Segredo longo com que o Agente Local faz poll — nunca digitado por humano."""
    return secrets.token_urlsafe(32)


def generate_agent_token() -> str:
    """Token opaco de 256 bits do agente pareado (Seção 4 — nunca JWT: revogar
    é só apagar a linha, sem lista de bloqueio)."""
    return secrets.token_urlsafe(32)


def generate_agent_id() -> str:
    return secrets.token_hex(8)


def hash_token(token: str) -> str:
    """SHA-256 — o banco guarda só isto, nunca o token cru (Seção 4)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
