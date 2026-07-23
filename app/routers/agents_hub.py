"""Hub WebSocket do Agente Local + gestão de agentes pareados.

O backend aqui é só o mensageiro (Seção 0 do esquema): repassa comando pro
agente certo e coleta resultado/auditoria. A DECISÃO de tier e a execução são
sempre do agente, na máquina do usuário — este arquivo nunca autoriza nada
perigoso, só encaminha.
"""
import asyncio
import hashlib
import json
import time

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .. import db
from ..security import hash_token, require_token

router = APIRouter()

# Genesis da cadeia de hash da auditoria (Seção 13.1). A primeira linha aponta
# pra isto; daí em diante cada linha aponta pro hash da anterior.
_AUDIT_GENESIS = "0" * 64

# Campos que entram no hash, em ordem fixa. Mudar esta lista/ordem invalida a
# verificação de logs antigos — só mexer com migração pensada.
_AUDIT_FIELDS = ("agent_id", "ts", "action_type", "target", "tier", "decision", "result", "chat_id", "message_id")


def _canonical_audit(rec: dict) -> str:
    """Serialização determinística (chaves ordenadas, sem espaço) do registro +
    prev_hash. É o que vira o SHA-256 — precisa ser idêntica na escrita e na
    verificação, então nada de depender de ordem de dict ou de float variável."""
    payload = {k: rec.get(k) for k in _AUDIT_FIELDS}
    payload["prev_hash"] = rec.get("prev_hash")
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _audit_hash(rec: dict) -> str:
    return hashlib.sha256(_canonical_audit(rec).encode("utf-8")).hexdigest()


def verify_audit_chain(conn) -> dict:
    """Percorre TODA a audit_log em ordem de id e confere a cadeia. Linhas
    antigas (pré-migração, hash NULL) formam um prefixo não-encadeado: são
    puladas e a cadeia real começa da primeira linha com hash (que foi escrita
    apontando pro genesis, já que a linha anterior tinha hash NULL). Qualquer
    adulteração/reordenação/remoção no trecho encadeado quebra a verificação."""
    rows = conn.execute("SELECT * FROM audit_log ORDER BY id ASC").fetchall()
    prev = _AUDIT_GENESIS
    legacy = 0
    chained = 0
    for r in rows:
        if r["hash"] is None:
            legacy += 1
            continue
        rec = {k: r[k] for k in _AUDIT_FIELDS}
        rec["prev_hash"] = r["prev_hash"]
        if r["prev_hash"] != prev or r["hash"] != _audit_hash(rec):
            return {"ok": False, "count": len(rows), "chained": chained, "legacy": legacy, "broken_at": r["id"]}
        prev = r["hash"]
        chained += 1
    return {"ok": True, "count": len(rows), "chained": chained, "legacy": legacy}


class _Hub:
    """Registro em memória dos agentes online (agent_id -> WebSocket).

    Só conexões vivas. A verdade persistente é a tabela paired_agents; isto é
    o mapa efêmero de quem está conectado agora.
    """

    def __init__(self):
        self._live: dict[str, WebSocket] = {}

    async def connect(self, agent_id: str, ws: WebSocket):
        # Se o mesmo agente reconecta, derruba a conexão antiga.
        old = self._live.get(agent_id)
        if old is not None:
            try:
                await old.close()
            except Exception:  # noqa: BLE001
                pass
        self._live[agent_id] = ws

    def disconnect(self, agent_id: str, ws: WebSocket):
        if self._live.get(agent_id) is ws:
            self._live.pop(agent_id, None)

    def is_online(self, agent_id: str) -> bool:
        return agent_id in self._live

    async def send(self, agent_id: str, payload: dict) -> bool:
        ws = self._live.get(agent_id)
        if ws is None:
            return False
        await ws.send_text(json.dumps(payload, ensure_ascii=False))
        return True


hub = _Hub()


def _authenticate_agent(token: str | None) -> str | None:
    """Devolve agent_id se o token bate com um agente pareado e não revogado."""
    if not token:
        return None
    token_hash = hash_token(token)
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT agent_id FROM paired_agents WHERE token_hash = ? AND revoked_at IS NULL",
            (token_hash,),
        ).fetchone()
    return row["agent_id"] if row else None


def _write_audit(agent_id: str, msg: dict):
    with db.get_conn() as conn:
        # prev_hash = hash da última linha (por id). WAL serializa escritas, e o
        # SELECT+INSERT rodam na mesma conexão/transação — pro caso de 1 usuário
        # com 1 agente (o alvo deste projeto) a janela de corrida é desprezível.
        last = conn.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = last["hash"] if last and last["hash"] else _AUDIT_GENESIS
        rec = {
            "agent_id": agent_id,
            "ts": time.time(),
            "action_type": str(msg.get("action_type", ""))[:40],
            "target": str(msg.get("target", ""))[:500],
            "tier": int(msg.get("tier", 0)),
            "decision": str(msg.get("decision", ""))[:20],
            "result": str(msg.get("result", ""))[:500],
            "chat_id": msg.get("chat_id"),
            "message_id": msg.get("message_id"),
            "prev_hash": prev_hash,
        }
        rec["hash"] = _audit_hash(rec)
        conn.execute(
            "INSERT INTO audit_log "
            "(agent_id, ts, action_type, target, tier, decision, result, chat_id, message_id, prev_hash, hash) "
            "VALUES (:agent_id, :ts, :action_type, :target, :tier, :decision, :result, :chat_id, :message_id, :prev_hash, :hash)",
            rec,
        )


@router.websocket("/ws/agent")
async def agent_ws(ws: WebSocket):
    # Header Authorization: Bearer <agent_token>. Query param como fallback pra
    # clientes WS que não deixam setar header (alguns ambientes do Node).
    auth = ws.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else ws.query_params.get("token")
    agent_id = _authenticate_agent(token)
    if agent_id is None:
        # ACEITA antes de fechar com o code — fechar pré-accept vira uma
        # rejeição de handshake HTTP (sem 101), e a maioria dos clientes WS
        # reais (inclusive o WebSocket nativo do Node) não expõe close.code
        # nesse caso, só um "error" genérico. Isso quebrava o cliente do
        # Agente Local: ele não conseguia distinguir "token inválido" (não
        # adianta reconectar) de "backend fora do ar" (vale reconectar).
        # Aceitar e fechar em seguida entrega o code 4401 de verdade.
        await ws.accept()
        await ws.close(code=4401)  # não autorizado
        return

    await ws.accept()
    await hub.connect(agent_id, ws)
    with db.get_conn() as conn:
        conn.execute("UPDATE paired_agents SET last_seen_at = ? WHERE agent_id = ?", (time.time(), agent_id))

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type")
            if mtype == "heartbeat":
                with db.get_conn() as conn:
                    conn.execute("UPDATE paired_agents SET last_seen_at = ? WHERE agent_id = ?", (time.time(), agent_id))
            elif mtype == "audit":
                _write_audit(agent_id, msg)
            elif mtype == "result":
                _pending_results.resolve(msg.get("id"), msg)
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(agent_id, ws)


class _PendingResults:
    """Correlaciona comando enviado (id) com o result que volta pelo WS."""

    def __init__(self):
        self._futures: dict[str, asyncio.Future] = {}

    def new(self, cmd_id: str) -> asyncio.Future:
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._futures[cmd_id] = fut
        return fut

    def resolve(self, cmd_id, payload):
        fut = self._futures.pop(cmd_id, None)
        if fut and not fut.done():
            fut.set_result(payload)

    def cancel(self, cmd_id: str):
        self._futures.pop(cmd_id, None)


_pending_results = _PendingResults()


# ---------------- Gestão (todas exigem token de sessão) ----------------
class CommandIn(BaseModel):
    action: str
    args: dict = {}
    chat_id: str | None = None
    message_id: str | None = None
    timeout: float = 60.0


@router.post("/api/agents/{agent_id}/command", dependencies=[Depends(require_token)])
async def send_command(agent_id: str, body: CommandIn):
    """Envia um comando pro agente e espera o resultado (Seção 12).

    O backend só encaminha — quem decide o tier e executa (ou pede confirmação
    local) é o agente. Este endpoint devolve o que o agente respondeu.
    """
    if not hub.is_online(agent_id):
        raise HTTPException(status_code=409, detail="Agente offline.")
    cmd_id = f"{agent_id}:{time.time_ns()}"
    fut = _pending_results.new(cmd_id)
    sent = await hub.send(agent_id, {
        "type": "command", "id": cmd_id, "action": body.action, "args": body.args,
        "chat_id": body.chat_id, "message_id": body.message_id,
    })
    if not sent:
        _pending_results.cancel(cmd_id)
        raise HTTPException(status_code=409, detail="Agente offline.")
    try:
        result = await asyncio.wait_for(fut, timeout=max(1.0, min(body.timeout, 300.0)))
    except asyncio.TimeoutError:
        _pending_results.cancel(cmd_id)
        raise HTTPException(status_code=504, detail="O agente não respondeu a tempo.")
    return result


@router.get("/api/agents", dependencies=[Depends(require_token)])
def list_agents():
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT agent_id, name, platform, created_at, last_seen_at, revoked_at "
            "FROM paired_agents ORDER BY created_at DESC"
        ).fetchall()
    return {"agents": [
        {
            "agent_id": r["agent_id"], "name": r["name"], "platform": r["platform"],
            "created_at": r["created_at"], "last_seen_at": r["last_seen_at"],
            "revoked": r["revoked_at"] is not None,
            "online": hub.is_online(r["agent_id"]) and r["revoked_at"] is None,
        }
        for r in rows
    ]}


@router.post("/api/agents/{agent_id}/revoke", dependencies=[Depends(require_token)])
async def revoke_agent(agent_id: str):
    with db.get_conn() as conn:
        cur = conn.execute(
            "UPDATE paired_agents SET revoked_at = ?, token_hash = '' WHERE agent_id = ? AND revoked_at IS NULL",
            (time.time(), agent_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Agente não encontrado (ou já revogado).")
    await hub.send(agent_id, {"type": "revoked"})
    return {"ok": True}


@router.get("/api/audit", dependencies=[Depends(require_token)])
def get_audit(limit: int = 100, agent_id: str | None = None):
    limit = max(1, min(limit, 500))
    with db.get_conn() as conn:
        if agent_id:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE agent_id = ? ORDER BY ts DESC LIMIT ?", (agent_id, limit)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    return {"entries": [dict(r) for r in rows]}


@router.get("/api/audit/verify", dependencies=[Depends(require_token)])
def audit_verify():
    """Confere a cadeia de hash de TODA a auditoria (Seção 13.1). Global de
    propósito — a cadeia cruza agentes na ordem de escrita; filtrar por agente
    quebraria a continuidade. Devolve o id da primeira linha adulterada, se
    houver."""
    with db.get_conn() as conn:
        return verify_audit_chain(conn)


class PolicyIn(BaseModel):
    allowed_roots: list[str]


@router.get("/api/agents/{agent_id}/policy", dependencies=[Depends(require_token)])
def get_policy(agent_id: str):
    with db.get_conn() as conn:
        row = conn.execute("SELECT allowed_roots FROM paired_agents WHERE agent_id = ?", (agent_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Agente não encontrado.")
    try:
        roots = json.loads(row["allowed_roots"])
    except (json.JSONDecodeError, TypeError):
        roots = []
    return {"allowed_roots": roots}


@router.put("/api/agents/{agent_id}/policy", dependencies=[Depends(require_token)])
async def set_policy(agent_id: str, body: PolicyIn):
    roots = [str(p).strip() for p in body.allowed_roots if str(p).strip()]
    with db.get_conn() as conn:
        cur = conn.execute(
            "UPDATE paired_agents SET allowed_roots = ? WHERE agent_id = ?",
            (json.dumps(roots, ensure_ascii=False), agent_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Agente não encontrado.")
    # Avisa o agente pra recarregar a política sem precisar reparear.
    await hub.send(agent_id, {"type": "policy_update", "allowed_roots": roots})
    return {"ok": True, "allowed_roots": roots}
