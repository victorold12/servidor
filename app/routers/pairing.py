"""Pareamento do Agente Local — RFC 8628 (Device Authorization Grant), estilo
Smart TV. Contratos e por quês completos em docs/SEGURANCA-AGENTE-LOCAL.md,
Seções 3 e 12.

Auth destes endpoints — deliberadamente NÃO é o `protected` genérico do main.py:
- /pair/start e /pair/poll: sem BACKEND_TOKEN. O agente ainda não tem token
  nenhum quando chama — é exatamente isso que estes endpoints resolvem.
  Protegidos por um rate limit dedicado (abaixo), não pela sessão.
- /pair/confirm e /pair/deny: exigem o token de sessão — quem chama é você,
  já logado no site, confirmando um pareamento que pediu.
"""
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import db
from ..security import (
    format_user_code,
    generate_agent_id,
    generate_agent_token,
    generate_device_code,
    generate_user_code,
    hash_token,
    normalize_user_code,
    require_token,
)

router = APIRouter()

PAIRING_TTL = 600     # 10 minutos (Seção 3)
POLL_INTERVAL = 3     # segundos sugeridos entre polls
MAX_ATTEMPTS = 5      # Seção 3 — trava depois de 5 tentativas erradas


# ---------------- Rate limit dedicado (Seção 14 — não o genérico de main.py) ----------------
# Poll legítimo bate a cada ~3s por até 10 min (~200 chamadas); o limite geral
# do backend (30/5min) bloquearia isso. Aqui o orçamento é por endpoint.
_hits: dict[str, list[float]] = defaultdict(list)
_START_LIMIT, _START_WINDOW = 10, 300.0    # 10 pareamentos iniciados / 5 min / IP
_POLL_LIMIT, _POLL_WINDOW = 250, 600.0     # cobre poll a cada 3s por 10 min, com folga


def _throttle(request: Request, bucket: str, limit: int, window: float):
    ip = request.client.host if request.client else "unknown"
    key = f"{bucket}:{ip}"
    now = time.time()
    hits = _hits[key]
    while hits and hits[0] < now - window:
        hits.pop(0)
    if len(hits) >= limit:
        raise HTTPException(status_code=429, detail="Muitas tentativas — aguarde.")
    hits.append(now)


class StartIn(BaseModel):
    name: str
    platform: str


class PollIn(BaseModel):
    device_code: str


class UserCodeIn(BaseModel):
    user_code: str


@router.post("/pair/start")
def pair_start(body: StartIn, request: Request):
    _throttle(request, "start", _START_LIMIT, _START_WINDOW)
    device_code = generate_device_code()
    user_code = generate_user_code()
    now = time.time()
    with db.get_conn() as conn:
        # Varre lixo de pendings já expirados por tempo (ninguém pollou pra
        # limpar). Barato e mantém a tabela pequena sem cron.
        conn.execute("DELETE FROM pending_pairings WHERE expires_at < ?", (now,))
        conn.execute(
            "INSERT INTO pending_pairings "
            "(device_code_hash, user_code, name, platform, created_at, expires_at, approved, attempts) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, 0)",
            (
                hash_token(device_code), user_code,
                body.name.strip()[:80] or "Dispositivo", body.platform.strip()[:40] or "desconhecido",
                now, now + PAIRING_TTL,
            ),
        )
    return {
        "device_code": device_code,
        "user_code": format_user_code(user_code),
        "interval": POLL_INTERVAL,
        "expires_in": PAIRING_TTL,
    }


@router.post("/pair/poll")
def pair_poll(body: PollIn, request: Request):
    _throttle(request, "poll", _POLL_LIMIT, _POLL_WINDOW)
    device_hash = hash_token(body.device_code)
    now = time.time()
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM pending_pairings WHERE device_code_hash = ?", (device_hash,)
        ).fetchone()
        if row is None:
            return {"status": "expired"}
        # Ordem importa: expirado por tempo vem antes de negado/travado, e os
        # dois são status DISTINTOS pro agente (Seção 12) — não colapsam num só.
        if row["expires_at"] < now:
            conn.execute("DELETE FROM pending_pairings WHERE device_code_hash = ?", (device_hash,))
            return {"status": "expired"}
        if row["attempts"] >= MAX_ATTEMPTS:
            # Você negou explicitamente, ou travou por tentativas erradas.
            # Só agora limpamos — deletar antes faria o poll ver "expired".
            conn.execute("DELETE FROM pending_pairings WHERE device_code_hash = ?", (device_hash,))
            return {"status": "denied"}
        if not row["approved"]:
            return {"status": "pending"}

        # Aprovado: emite o agente + token e consome o pending numa tacada só.
        agent_id = generate_agent_id()
        token = generate_agent_token()
        conn.execute(
            "INSERT INTO paired_agents "
            "(agent_id, user_id, name, platform, token_hash, allowed_roots, created_at, last_seen_at) "
            "VALUES (?, 'victor', ?, ?, ?, '[]', ?, ?)",
            (agent_id, row["name"], row["platform"], hash_token(token), now, now),
        )
        conn.execute("DELETE FROM pending_pairings WHERE device_code_hash = ?", (device_hash,))
        return {
            "status": "approved",
            "agent_id": agent_id,
            "agent_token": token,
            "allowed_roots": [],
        }


@router.post("/pair/confirm", dependencies=[Depends(require_token)])
def pair_confirm(body: UserCodeIn):
    code = normalize_user_code(body.user_code)
    now = time.time()
    with db.get_conn() as conn:
        # Só pendings vivos, não-aprovados e ainda NÃO travados entram na conta.
        active = conn.execute(
            "SELECT * FROM pending_pairings WHERE expires_at > ? AND approved = 0 AND attempts < ?",
            (now, MAX_ATTEMPTS),
        ).fetchall()
        match = next((r for r in active if r["user_code"] == code), None)
        if match is None:
            # Não achou: cada pareamento ativo absorve uma "tentativa errada"
            # (não dá pra saber qual código a pessoa tinha em mente — Seção 3).
            # Ao chegar em MAX_ATTEMPTS a linha NÃO é deletada aqui — fica marcada
            # (attempts = MAX) pra que o poll do agente reporte "denied", não
            # "expired". A limpeza acontece no poll seguinte.
            for r in active:
                conn.execute(
                    "UPDATE pending_pairings SET attempts = ? WHERE device_code_hash = ?",
                    (r["attempts"] + 1, r["device_code_hash"]),
                )
            # IMPORTANTE: não levantar HTTPException aqui dentro. get_conn() só
            # commita no caminho SEM exceção — levantar agora descartaria o
            # incremento de attempts (a trava de brute-force). Sai do `with`
            # pra commitar, e só então sinaliza o erro (abaixo).
        else:
            conn.execute(
                "UPDATE pending_pairings SET approved = 1, approved_by = 'victor' WHERE device_code_hash = ?",
                (match["device_code_hash"],),
            )
    if match is None:
        raise HTTPException(status_code=400, detail="Código inválido ou expirado.")
    return {"ok": True, "name": match["name"], "platform": match["platform"]}


@router.post("/pair/deny", dependencies=[Depends(require_token)])
def pair_deny(body: UserCodeIn):
    code = normalize_user_code(body.user_code)
    now = time.time()
    with db.get_conn() as conn:
        active = conn.execute(
            "SELECT * FROM pending_pairings WHERE expires_at > ? AND approved = 0 AND attempts < ?",
            (now, MAX_ATTEMPTS),
        ).fetchall()
        match = next((r for r in active if r["user_code"] == code), None)
        if match is None:
            raise HTTPException(status_code=400, detail="Código inválido ou expirado.")
        # Negar não deleta na hora: marca como travado (attempts = MAX) pra que o
        # poll do agente veja "denied" e mostre a mensagem certa. Some no poll seguinte.
        conn.execute(
            "UPDATE pending_pairings SET attempts = ? WHERE device_code_hash = ?",
            (MAX_ATTEMPTS, match["device_code_hash"]),
        )
    return {"ok": True}
