"""/api/backup — export e import do que é seu (Seção 5 do prompt mestre).

O PDF pede "export periódico do banco (conversas + memória) pra um storage seu".
A parte que o backend deve fazer é gerar o pacote e aceitá-lo de volta; para
onde ele vai (Drive, S3, pendrive) é escolha de quem baixa — o backend não
guarda credencial de storage de terceiro só pra isso.

O que entra no pacote: memória (grafo + camada diária), agentes pareados e o log
de auditoria. O que NÃO entra: token de agente e nada que sirva pra se passar por
um dispositivo pareado. Um backup vazado não pode virar acesso ao PC.

O import é o oposto de destrutivo por padrão: `mode=merge` acrescenta,
`mode=replace` troca — e replace precisa ser pedido explicitamente.
"""
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db
from .agents_hub import verify_audit_chain

router = APIRouter()

FORMAT = "vtz-backup/1"
_USER = "victor"

# Colunas que NUNCA saem no export. token_hash é o que autentica um agente:
# no backup ele não tem utilidade legítima e vazado vira credencial.
_AGENTE_PUBLICO = ("agent_id", "name", "platform", "created_at", "last_seen_at", "revoked_at")


@router.get("/backup/export")
def export_all():
    """Devolve o pacote inteiro em JSON, pronto pra salvar onde o usuário quiser."""
    with db.get_conn() as conn:
        nodes = conn.execute(
            "SELECT node_id, label, type, created_at FROM memory_nodes WHERE user_id = ? ORDER BY rowid",
            (_USER,)).fetchall()
        edges = conn.execute(
            "SELECT source, relation, target, confidence FROM memory_edges WHERE user_id = ? ORDER BY id",
            (_USER,)).fetchall()
        daily = conn.execute(
            "SELECT day, summary, fact_count, updated_at FROM memory_daily WHERE user_id = ? ORDER BY day",
            (_USER,)).fetchall()

        cols = {r["name"] for r in conn.execute("PRAGMA table_info(paired_agents)")}
        campos = [c for c in _AGENTE_PUBLICO if c in cols]
        agentes = conn.execute(
            f"SELECT {', '.join(campos)} FROM paired_agents ORDER BY created_at").fetchall()

        audit = conn.execute(
            "SELECT agent_id, ts, action_type, target, tier, decision, result, "
            "prev_hash, hash FROM audit_log ORDER BY id").fetchall()

        integridade = verify_audit_chain(conn)

    return {
        "format": FORMAT,
        "exported_at": time.time(),
        "memory": {
            "nodes": [dict(r) for r in nodes],
            "edges": [dict(r) for r in edges],
            "daily": [dict(r) for r in daily],
        },
        "agents": [dict(r) for r in agentes],
        "audit": [dict(r) for r in audit],
        "audit_chain_ok": bool(integridade.get("ok")),
        "note": ("Tokens de agente ficam fora de propósito: com eles, este arquivo "
                 "viraria acesso ao seu PC. Depois de restaurar, refaça o pareamento."),
    }


class ImportIn(BaseModel):
    format: str | None = None
    memory: dict = {}
    mode: str = "merge"          # merge (padrão, acrescenta) | replace (troca)


@router.post("/backup/import")
def import_all(body: ImportIn):
    """Restaura a memória de um pacote.

    Só a memória é restaurada. Agente pareado não volta por backup — pareamento
    é uma decisão presencial (código de 8 caracteres, confirmação no PC), e
    recriar isso a partir de arquivo derrubaria a garantia da Seção 8. Auditoria
    também não volta: ela é um registro encadeado do que aconteceu NESTE banco;
    injetar linhas de outro quebraria a verificação da cadeia.
    """
    if body.format and body.format != FORMAT:
        raise HTTPException(
            status_code=400,
            detail=f"Formato desconhecido: {body.format!r} (esperado {FORMAT!r}).")
    if body.mode not in ("merge", "replace"):
        raise HTTPException(status_code=400, detail="mode deve ser 'merge' ou 'replace'.")

    nodes = body.memory.get("nodes") or []
    edges = body.memory.get("edges") or []
    daily = body.memory.get("daily") or []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise HTTPException(status_code=400, detail="memory.nodes e memory.edges devem ser listas.")

    validos = [n for n in nodes
               if isinstance(n, dict) and n.get("node_id") and n.get("label")]
    ids = {n["node_id"] for n in validos}
    # aresta órfã não entra: o grafo não deve referenciar nó que não existe
    arestas = [e for e in edges
               if isinstance(e, dict) and e.get("source") in ids and e.get("target") in ids]

    with db.get_conn() as conn:
        if body.mode == "replace":
            for t in ("memory_nodes", "memory_edges", "memory_daily", "memory_vectors"):
                conn.execute(f"DELETE FROM {t} WHERE user_id = ?", (_USER,))

        conn.executemany(
            "INSERT INTO memory_nodes (user_id, node_id, label, type, created_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id, node_id) DO UPDATE SET "
            "label = excluded.label, type = excluded.type",
            [(_USER, n["node_id"], str(n["label"])[:200], n.get("type") or "fato",
              n.get("created_at")) for n in validos])

        existentes = {
            (r["source"], r["relation"], r["target"])
            for r in conn.execute(
                "SELECT source, relation, target FROM memory_edges WHERE user_id = ?", (_USER,))
        }
        conn.executemany(
            "INSERT INTO memory_edges (user_id, source, relation, target, confidence) "
            "VALUES (?, ?, ?, ?, ?)",
            [(_USER, e["source"], e.get("relation") or "relaciona", e["target"],
              float(e.get("confidence") or 0.9))
             for e in arestas
             if (e["source"], e.get("relation") or "relaciona", e["target"]) not in existentes])

        conn.executemany(
            "INSERT INTO memory_daily (user_id, day, summary, fact_count, updated_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id, day) DO UPDATE SET "
            "summary = excluded.summary, fact_count = excluded.fact_count, "
            "updated_at = excluded.updated_at",
            [(_USER, d["day"], d.get("summary") or "", int(d.get("fact_count") or 0),
              float(d.get("updated_at") or time.time()))
             for d in daily if isinstance(d, dict) and d.get("day")])

        totais = {
            "nodes": conn.execute(
                "SELECT COUNT(*) c FROM memory_nodes WHERE user_id = ?", (_USER,)).fetchone()["c"],
            "edges": conn.execute(
                "SELECT COUNT(*) c FROM memory_edges WHERE user_id = ?", (_USER,)).fetchone()["c"],
            "daily": conn.execute(
                "SELECT COUNT(*) c FROM memory_daily WHERE user_id = ?", (_USER,)).fetchone()["c"],
        }

    return {
        "ok": True,
        "mode": body.mode,
        "importados": {"nodes": len(validos), "edges": len(arestas), "daily": len(daily)},
        "descartados": {"nodes": len(nodes) - len(validos),
                        "edges": len(edges) - len(arestas)},
        "totais_agora": totais,
        "note": ("Vetores de busca não vêm no pacote (dependem do modelo de "
                 "embedding em uso) — rode /api/memory/reindex depois de restaurar."),
    }


# =====================================================================
# Backup automático agendado (app/autobackup.py)
# =====================================================================
from .. import autobackup  # noqa: E402


@router.get("/backup/auto")
def auto_status():
    """Estado do backup automático, com o aviso de ONDE o snapshot mora.

    O aviso vai na resposta de propósito: "backup na nuvem" e "backup no mesmo
    disco do banco" são coisas diferentes, e quem lê precisa saber qual das duas
    tem antes de confiar.
    """
    return autobackup.status()


@router.post("/backup/auto/run")
def auto_run():
    """Tira um snapshot agora, fora do agendamento."""
    try:
        return {"ok": True, **autobackup.escreve_snapshot()}
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Não consegui escrever o snapshot: {e}") from e


@router.get("/backup/auto/list")
def auto_list():
    return {"snapshots": autobackup.lista(), "pasta": str(autobackup.diretorio())}


@router.get("/backup/auto/download/{arquivo}")
def auto_download(arquivo: str):
    """Baixa um snapshot. Só nome de arquivo — nada de caminho.

    `..` ou barra aqui viraria leitura de qualquer arquivo do servidor, então o
    nome é validado contra o padrão exato que escreve_snapshot() usa.
    """
    import re

    from fastapi.responses import FileResponse

    if not re.fullmatch(r"jarvis-\d{8}-\d{6}\.json\.gz", arquivo):
        raise HTTPException(status_code=400, detail="Nome de snapshot inválido.")
    caminho = autobackup.diretorio() / arquivo
    if not caminho.is_file():
        raise HTTPException(status_code=404, detail="Snapshot não encontrado.")
    return FileResponse(caminho, media_type="application/gzip", filename=arquivo)
