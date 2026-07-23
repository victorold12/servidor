"""Banco SQLite — pareamento e auditoria do Agente Local (Seção 11 do esquema
em docs/SEGURANCA-AGENTE-LOCAL.md).

Arquivo único, sem serviço externo — mesma filosofia do resto do backend (zero
infraestrutura extra pra um usuário só). Migra pra Postgres quando precisar de
multi-dispositivo de verdade; o esquema já é relacional simples de portar.
"""
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

# JARVIS_DB_PATH permite apontar pra um banco isolado (ex.: teste de integração
# do Agente Local, que sobe este backend de verdade num processo separado e não
# pode tocar no jarvis.db real). Sem a env var, é o arquivo de sempre.
_DB_PATH = Path(os.environ.get("JARVIS_DB_PATH") or (Path(__file__).resolve().parent.parent / "jarvis.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS paired_agents (
    agent_id      TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL DEFAULT 'victor',
    name          TEXT NOT NULL,
    platform      TEXT NOT NULL,
    token_hash    TEXT NOT NULL,
    allowed_roots TEXT NOT NULL DEFAULT '[]',
    created_at    REAL NOT NULL,
    last_seen_at  REAL,
    revoked_at    REAL
);

CREATE TABLE IF NOT EXISTS pending_pairings (
    device_code_hash TEXT PRIMARY KEY,
    user_code        TEXT NOT NULL,
    name             TEXT NOT NULL,
    platform         TEXT NOT NULL,
    created_at       REAL NOT NULL,
    expires_at       REAL NOT NULL,
    approved         INTEGER NOT NULL DEFAULT 0,
    approved_by      TEXT,
    attempts         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id     TEXT NOT NULL,
    ts           REAL NOT NULL,
    action_type  TEXT NOT NULL,
    target       TEXT NOT NULL,
    tier         INTEGER NOT NULL,
    decision     TEXT NOT NULL,
    result       TEXT NOT NULL,
    chat_id      TEXT,
    message_id   TEXT,
    -- Cadeia de hash (Seção 13.1, absorvido do JarvisAI): cada linha guarda o
    -- hash da anterior; adulterar/reordenar/apagar no meio quebra verify_chain().
    prev_hash    TEXT,
    hash         TEXT
);

-- Grafo de memória de longo prazo (Seção 7): o BACKEND é a fonte única. App,
-- extensão e desktop leem/escrevem aqui e mantêm só cache descartável — não
-- existe "sincronizar duas verdades". Normalizado (nós + arestas) de propósito,
-- pra portar pra Postgres/pgvector depois sem virar um blob opaco.
CREATE TABLE IF NOT EXISTS memory_nodes (
    user_id   TEXT NOT NULL DEFAULT 'victor',
    node_id   TEXT NOT NULL,
    label     TEXT NOT NULL,
    type      TEXT NOT NULL DEFAULT 'fato',
    PRIMARY KEY (user_id, node_id)
);

CREATE TABLE IF NOT EXISTS memory_edges (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL DEFAULT 'victor',
    source     TEXT NOT NULL,
    relation   TEXT NOT NULL,
    target     TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.9
);

CREATE INDEX IF NOT EXISTS idx_audit_agent_ts ON audit_log(agent_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_pending_user_code ON pending_pairings(user_code);
CREATE INDEX IF NOT EXISTS idx_memory_edges_user ON memory_edges(user_id);
"""


@contextmanager
def get_conn():
    """Conexão transacional: commita no fim SE o bloco terminou sem exceção;
    qualquer exceção descarta tudo (rollback implícito ao fechar sem commit).

    Isso é de propósito — dá atomicidade (ex.: no poll aprovado, inserir o agente
    e apagar o pending acontecem juntos ou não acontecem). MAS tem uma pegadinha:
    se você faz um write que DEVE persistir e logo depois levanta HTTPException
    dentro do `with`, o commit é pulado e o write some. Nesse caso, feche o `with`
    primeiro (pra commitar) e levante a exceção FORA dele. Ver pair_confirm em
    routers/pairing.py pra o padrão certo.
    """
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(_SCHEMA)
        _migrate(conn)


def _migrate(conn):
    """Migrações idempotentes pra bancos que já existem (o CREATE ... IF NOT
    EXISTS não adiciona colunas novas a uma tabela antiga)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(audit_log)")}
    if "prev_hash" not in cols:
        conn.execute("ALTER TABLE audit_log ADD COLUMN prev_hash TEXT")
    if "hash" not in cols:
        conn.execute("ALTER TABLE audit_log ADD COLUMN hash TEXT")


def now() -> float:
    return time.time()
