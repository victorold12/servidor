"""Espelho das conversas do painel (Seção 7).

QUEM É A FONTE DA VERDADE: o navegador. A conversa é escrita no localStorage e
continua funcionando sem backend nenhum. Isto aqui é o espelho — é o que faz a
conversa aparecer no outro dispositivo e sobreviver a "limpar o cache".

REGRA DE CONFLITO: última escrita ganha, por conversa, comparando `updated_at`.
Não existe merge de lista de mensagens, de propósito: juntar as mensagens de
dois dispositivos produziria uma conversa que nunca aconteceu. Quem escreveu
mais tarde leva a conversa inteira, e a resposta diz o que foi recusado por ser
mais velho — o painel mostra isso em vez de fingir que subiu tudo.

APAGAR é lápide (`deleted_at`), não DELETE: sem isso, um dispositivo que ainda
não sincronizou reenviaria a conversa apagada e ela voltaria do nada.
"""
import json
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db

router = APIRouter()

_USER = "victor"

# Teto por conversa. Uma conversa é texto; 4 MB é muito mais do que qualquer
# uso real e evita que um payload defeituoso encha o banco.
_MAX_PAYLOAD = 4 * 1024 * 1024
# Teto por requisição, pra o primeiro envio de um histórico grande não virar um
# POST gigante. O painel manda em lotes.
_MAX_LOTE = 200
# Folga pra diferença de relógio entre dispositivo e servidor. Acima disso o
# carimbo é considerado adiantado e trazido pra hora do servidor.
_TOLERANCIA_RELOGIO = 60.0


class ConvIn(BaseModel):
    id: str
    title: str | None = None
    pinned: bool = False
    updated_at: float
    messages: list[dict] = []
    # o painel guarda mais coisa por conversa (projeto, agente, anexos...):
    # vai tudo junto em `extra` e volta igual, sem o servidor opinar
    extra: dict = {}


class PushIn(BaseModel):
    conversations: list[ConvIn] = []
    deleted: list[str] = []


def _linha_para_conversa(r) -> dict:
    corpo = json.loads(r["payload"])
    corpo["id"] = r["conv_id"]
    corpo["updated_at"] = r["updated_at"]
    return corpo


@router.get("/conversations")
def listar(since: float = 0.0, include_payload: bool = True, limit: int = 500):
    """Conversas com updated_at > `since`.

    `include_payload=false` devolve só o índice (id/título/updated_at), que é o
    suficiente pro painel decidir o que precisa baixar sem trazer o histórico
    inteiro a cada checagem.
    """
    limit = max(1, min(limit, 2000))
    with db.get_conn() as conn:
        linhas = conn.execute(
            "SELECT conv_id, title, pinned, msg_count, updated_at, deleted_at, payload "
            "FROM conversations WHERE user_id = ? AND updated_at > ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (_USER, since, limit),
        ).fetchall()

    vivas, apagadas = [], []
    for r in linhas:
        if r["deleted_at"] is not None:
            apagadas.append({"id": r["conv_id"], "deleted_at": r["deleted_at"],
                             "updated_at": r["updated_at"]})
            continue
        if include_payload:
            vivas.append(_linha_para_conversa(r))
        else:
            vivas.append({"id": r["conv_id"], "title": r["title"],
                          "pinned": bool(r["pinned"]), "msg_count": r["msg_count"],
                          "updated_at": r["updated_at"]})
    return {"conversations": vivas, "deleted": apagadas,
            "server_time": time.time(), "since": since}


@router.put("/conversations")
def enviar(body: PushIn):
    """Sobe conversas. Só grava o que for MAIS NOVO que o que já está aqui.

    Devolve `recusadas` com o que veio mais velho — o painel usa isso pra saber
    que aquela conversa foi editada em outro dispositivo e precisa ser baixada,
    em vez de achar que o envio deu certo.
    """
    if len(body.conversations) > _MAX_LOTE:
        raise HTTPException(
            status_code=413,
            detail=f"Lote de {len(body.conversations)} conversas; o máximo é {_MAX_LOTE}. "
                   "Mande em partes.")

    agora = time.time()
    gravadas, recusadas, grandes, futuros = [], [], [], []

    with db.get_conn() as conn:
        for c in body.conversations:
            # Relógio adiantado é veneno pra "última escrita ganha": um carimbo
            # no futuro venceria TODO conflito daí em diante, e nenhum outro
            # dispositivo conseguiria mais atualizar essa conversa. Carimbo
            # adiantado além da tolerância é trazido pra hora do servidor —
            # edição não acontece no futuro.
            if c.updated_at > agora + _TOLERANCIA_RELOGIO:
                futuros.append({"id": c.id, "enviado_em": c.updated_at, "ajustado_para": agora})
                c.updated_at = agora
            corpo = {"title": c.title or "", "pinned": bool(c.pinned),
                     "messages": c.messages, **c.extra}
            texto = json.dumps(corpo, ensure_ascii=False)
            if len(texto.encode("utf-8")) > _MAX_PAYLOAD:
                grandes.append(c.id)
                continue

            atual = conn.execute(
                "SELECT updated_at, deleted_at FROM conversations "
                "WHERE user_id = ? AND conv_id = ?", (_USER, c.id)).fetchone()

            # apagada aqui e o envio não é mais novo: a lápide vence
            if atual is not None and atual["updated_at"] >= c.updated_at:
                recusadas.append({"id": c.id, "servidor_em": atual["updated_at"],
                                  "enviado_em": c.updated_at,
                                  "motivo": "apagada aqui depois" if atual["deleted_at"]
                                            else "versão do servidor é mais nova"})
                continue

            conn.execute(
                "INSERT INTO conversations "
                "(user_id, conv_id, title, pinned, msg_count, updated_at, synced_at, "
                " deleted_at, payload) VALUES (?,?,?,?,?,?,?,NULL,?) "
                "ON CONFLICT(user_id, conv_id) DO UPDATE SET "
                "  title=excluded.title, pinned=excluded.pinned, "
                "  msg_count=excluded.msg_count, updated_at=excluded.updated_at, "
                "  synced_at=excluded.synced_at, deleted_at=NULL, payload=excluded.payload",
                (_USER, c.id, c.title or "", 1 if c.pinned else 0, len(c.messages),
                 c.updated_at, agora, texto))
            gravadas.append(c.id)

        for cid in body.deleted[:_MAX_LOTE]:
            # lápide com o carimbo de agora: mais nova que qualquer versão que
            # outro dispositivo ainda tenha, então ela ganha o conflito
            conn.execute(
                "INSERT INTO conversations "
                "(user_id, conv_id, title, pinned, msg_count, updated_at, synced_at, "
                " deleted_at, payload) VALUES (?,?,'',0,0,?,?,?,'{}') "
                "ON CONFLICT(user_id, conv_id) DO UPDATE SET "
                "  updated_at=excluded.updated_at, synced_at=excluded.synced_at, "
                "  deleted_at=excluded.deleted_at, payload='{}', title='', msg_count=0",
                (_USER, cid, agora, agora, agora))

    resposta = {"ok": True, "gravadas": gravadas, "recusadas": recusadas,
                "apagadas": body.deleted[:_MAX_LOTE], "server_time": agora}
    if futuros:
        resposta["relogio_ajustado"] = futuros
        resposta["aviso_relogio"] = (
            f"{len(futuros)} conversa(s) vieram com data no futuro e foram carimbadas "
            "com a hora do servidor. O relógio deste dispositivo está adiantado — "
            "sem esse ajuste elas venceriam todo conflito futuro.")
    if grandes:
        resposta["grandes_demais"] = grandes
        resposta["aviso"] = (f"{len(grandes)} conversa(s) passaram de "
                             f"{_MAX_PAYLOAD // (1024 * 1024)} MB e não foram gravadas.")
    return resposta


@router.get("/conversations/{conv_id}")
def uma(conv_id: str):
    with db.get_conn() as conn:
        r = conn.execute(
            "SELECT conv_id, title, pinned, msg_count, updated_at, deleted_at, payload "
            "FROM conversations WHERE user_id = ? AND conv_id = ?",
            (_USER, conv_id)).fetchone()
    if r is None:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")
    if r["deleted_at"] is not None:
        raise HTTPException(status_code=410, detail="Conversa apagada.")
    return _linha_para_conversa(r)


@router.delete("/conversations/{conv_id}")
def apagar(conv_id: str):
    agora = time.time()
    with db.get_conn() as conn:
        existe = conn.execute(
            "SELECT 1 FROM conversations WHERE user_id = ? AND conv_id = ?",
            (_USER, conv_id)).fetchone()
        conn.execute(
            "INSERT INTO conversations "
            "(user_id, conv_id, title, pinned, msg_count, updated_at, synced_at, "
            " deleted_at, payload) VALUES (?,?,'',0,0,?,?,?,'{}') "
            "ON CONFLICT(user_id, conv_id) DO UPDATE SET "
            "  updated_at=excluded.updated_at, synced_at=excluded.synced_at, "
            "  deleted_at=excluded.deleted_at, payload='{}', title='', msg_count=0",
            (_USER, conv_id, agora, agora, agora))
    return {"ok": True, "id": conv_id, "existia": existe is not None, "deleted_at": agora}


@router.get("/conversations/_meta/status")
def status():
    """Resumo pro painel mostrar o estado da sincronização sem baixar nada."""
    with db.get_conn() as conn:
        r = conn.execute(
            "SELECT COUNT(*) AS vivas, MAX(updated_at) AS ultima, "
            "       SUM(msg_count) AS mensagens "
            "FROM conversations WHERE user_id = ? AND deleted_at IS NULL",
            (_USER,)).fetchone()
        lapides = conn.execute(
            "SELECT COUNT(*) AS n FROM conversations "
            "WHERE user_id = ? AND deleted_at IS NOT NULL", (_USER,)).fetchone()["n"]
    return {"conversas": r["vivas"] or 0, "mensagens": r["mensagens"] or 0,
            "lapides": lapides, "ultima_atualizacao": r["ultima"],
            "server_time": time.time()}
