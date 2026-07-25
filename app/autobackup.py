"""Backup automático do banco, por agendamento no próprio servidor.

SOBRE O NOME: isto grava no disco DO SERVIDOR, ao lado do banco. Se o backend
está publicado (Render e afins), esse disco é a nuvem de verdade. Se o backend
roda na tua máquina, é a MESMA máquina do banco — protege contra "apaguei sem
querer" e contra corromper o arquivo, mas NÃO contra o HD morrer. A rota de
status diz isso com essas palavras, pra ninguém achar que tem cópia fora de casa
quando não tem.

O que entra: memória em grafo, camada diária, conversas espelhadas e a lista de
dispositivos pareados SEM o token. O que não entra: token de pareamento (segredo
que não deve existir em cópia) e a auditoria (registro encadeado deste banco;
restaurar linhas de outro quebraria a verificação da cadeia).
"""
import asyncio
import gzip
import json
import os
import time
from pathlib import Path

from . import db
from .config import settings

_FORMAT = "jarvis-autobackup-1"


def diretorio() -> Path:
    """Onde os snapshots ficam. Ao lado do banco por padrão."""
    if settings.backup_dir:
        return Path(settings.backup_dir)
    return Path(db._DB_PATH).resolve().parent / "backups"


def _pacote() -> dict:
    """Monta o snapshot. Reusa as mesmas exclusões da exportação manual."""
    with db.get_conn() as conn:
        nos = [dict(r) for r in conn.execute(
            "SELECT user_id, node_id, label, type, created_at FROM memory_nodes ORDER BY rowid")]
        arestas = [dict(r) for r in conn.execute(
            "SELECT user_id, source, relation, target, confidence FROM memory_edges ORDER BY id")]
        diario = [dict(r) for r in conn.execute(
            "SELECT user_id, day, summary, fact_count, updated_at FROM memory_daily ORDER BY day")]
        conversas = [dict(r) for r in conn.execute(
            "SELECT user_id, conv_id, title, pinned, msg_count, updated_at, deleted_at, payload "
            "FROM conversations ORDER BY updated_at")]
        # token_hash fica FORA: segredo de pareamento não entra em cópia
        agentes = [dict(r) for r in conn.execute(
            "SELECT agent_id, name, platform, created_at, last_seen_at, revoked_at "
            "FROM paired_agents ORDER BY created_at")]

    return {
        "format": _FORMAT,
        "created_at": time.time(),
        "memory": {"nodes": nos, "edges": arestas, "daily": diario},
        "conversations": conversas,
        "agents": agentes,
        "note": "sem token de pareamento e sem auditoria — ver app/autobackup.py",
    }


def escreve_snapshot() -> dict:
    """Grava um snapshot .json.gz e aplica a retenção. Devolve o que fez."""
    destino = diretorio()
    destino.mkdir(parents=True, exist_ok=True)
    pacote = _pacote()
    nome = "jarvis-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + ".json.gz"
    caminho = destino / nome

    bruto = json.dumps(pacote, ensure_ascii=False).encode("utf-8")
    # escreve num temporário e renomeia: snapshot pela metade (queda no meio da
    # escrita) não pode virar o arquivo que você vai tentar restaurar depois
    tmp = caminho.with_suffix(".parcial")
    with gzip.open(tmp, "wb") as f:
        f.write(bruto)
    os.replace(tmp, caminho)

    removidos = aplica_retencao()
    return {
        "arquivo": str(caminho),
        "bytes": caminho.stat().st_size,
        "bytes_sem_compressao": len(bruto),
        "conversas": len(pacote["conversations"]),
        "nos": len(pacote["memory"]["nodes"]),
        "removidos_pela_retencao": removidos,
    }


def lista() -> list[dict]:
    d = diretorio()
    if not d.is_dir():
        return []
    itens = []
    for f in sorted(d.glob("jarvis-*.json.gz"), reverse=True):
        st = f.stat()
        itens.append({"arquivo": f.name, "bytes": st.st_size, "modificado_em": st.st_mtime})
    return itens


def aplica_retencao() -> list[str]:
    """Mantém os N mais recentes. Sem isto o disco enche em silêncio."""
    manter = max(1, settings.backup_keep)
    todos = lista()
    removidos = []
    for item in todos[manter:]:
        try:
            (diretorio() / item["arquivo"]).unlink()
            removidos.append(item["arquivo"])
        except OSError:
            pass
    return removidos


def status() -> dict:
    itens = lista()
    d = diretorio()
    local = "o disco do servidor"
    return {
        "ligado": bool(settings.backup_every_hours > 0),
        "cada_horas": settings.backup_every_hours,
        "manter": settings.backup_keep,
        "pasta": str(d),
        "existem": len(itens),
        "ultimo": itens[0] if itens else None,
        "onde": local,
        "aviso": (
            "O snapshot vai pro disco do servidor, na mesma máquina do banco. "
            "Se o backend está publicado na nuvem, essa é uma cópia fora do teu PC. "
            "Se o backend roda no teu PC, é o MESMO disco do banco: protege contra "
            "apagar sem querer ou corromper o arquivo, mas não contra o HD morrer — "
            "pra isso, baixe o backup de vez em quando."
        ),
    }


async def loop_agendado():
    """Tarefa de fundo. Só roda se BACKUP_EVERY_HOURS > 0 — desligado é o padrão,
    porque escrever no disco de alguém sem ele pedir não é papel do programa."""
    horas = settings.backup_every_hours
    if horas <= 0:
        return
    intervalo = max(0.25, horas) * 3600
    # o primeiro snapshot sai já no boot: o caso em que backup mais falta é
    # justamente quando ninguém percebeu que ele nunca rodou
    while True:
        try:
            r = escreve_snapshot()
            print(f"[autobackup] {r['arquivo']} ({r['bytes']} bytes, "
                  f"{r['conversas']} conversas)")
        except Exception as e:  # noqa: BLE001
            # falha de backup não pode derrubar o servidor
            print(f"[autobackup] falhou: {e}")
        await asyncio.sleep(intervalo)
