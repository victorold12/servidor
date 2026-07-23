"""/api/memory — grafo de memória de longo prazo (Seção 7 do esquema).

O BACKEND é a fonte única da verdade da memória. O site (e depois extensão e
desktop) leem com GET e escrevem o grafo inteiro com PUT — a lógica de fusão
(dedup, relações funcionais que substituem, poda por teto) roda no cliente e o
resultado é persistido aqui atômico. Assim não existe "conflito de sync": só
há uma verdade, e o cliente mantém só cache descartável.

Single-user por ora: user_id fixo 'victor' (mesmo default de paired_agents).
Multi-usuário é item futuro — a coluna user_id já está pronta pra isso.
"""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import db

router = APIRouter()

# Enquanto é mono-usuário, tudo vai pra este dono. A coluna já existe pra quando
# virar multi-usuário (Seção 5 — bônus futuro).
_USER = "victor"

# Tetos de segurança — o cliente já poda em ~120 nós (MEM_MAX_NODES), isto aqui
# é o guarda-costas do servidor contra um payload absurdo.
_MAX_NODES = 2000
_MAX_EDGES = 8000


class Node(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=200)
    type: str = "fato"


class Edge(BaseModel):
    source: str = Field(min_length=1, max_length=200)
    relation: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=200)
    confidence: float = 0.9


class Graph(BaseModel):
    nodes: list[Node] = []
    edges: list[Edge] = []


@router.get("/memory")
def get_memory():
    """Devolve o grafo inteiro do usuário."""
    with db.get_conn() as conn:
        nodes = conn.execute(
            "SELECT node_id AS id, label, type FROM memory_nodes WHERE user_id = ? ORDER BY rowid",
            (_USER,),
        ).fetchall()
        edges = conn.execute(
            "SELECT source, relation, target, confidence FROM memory_edges WHERE user_id = ? ORDER BY id",
            (_USER,),
        ).fetchall()
    return {"nodes": [dict(n) for n in nodes], "edges": [dict(e) for e in edges]}


@router.put("/memory")
def put_memory(graph: Graph):
    """Substitui o grafo inteiro do usuário, atômico (delete-all + insert numa
    transação — get_conn commita só se tudo der certo). O cliente manda o grafo
    já fundido; o servidor só persiste a nova verdade."""
    if len(graph.nodes) > _MAX_NODES or len(graph.edges) > _MAX_EDGES:
        return {"ok": False, "error": f"grafo grande demais (máx {_MAX_NODES} nós / {_MAX_EDGES} arestas)"}

    # Só mantém arestas cujos dois lados existem como nó — evita aresta órfã
    # persistida (o cliente já cuida disso, mas o servidor não confia cegamente).
    node_ids = {n.id for n in graph.nodes}
    edges = [e for e in graph.edges if e.source in node_ids and e.target in node_ids]

    with db.get_conn() as conn:
        conn.execute("DELETE FROM memory_nodes WHERE user_id = ?", (_USER,))
        conn.execute("DELETE FROM memory_edges WHERE user_id = ?", (_USER,))
        conn.executemany(
            "INSERT INTO memory_nodes (user_id, node_id, label, type) VALUES (?, ?, ?, ?)",
            [(_USER, n.id, n.label, n.type) for n in graph.nodes],
        )
        conn.executemany(
            "INSERT INTO memory_edges (user_id, source, relation, target, confidence) VALUES (?, ?, ?, ?, ?)",
            [(_USER, e.source, e.relation, e.target, e.confidence) for e in edges],
        )
    return {"ok": True, "nodes": len(graph.nodes), "edges": len(edges)}
