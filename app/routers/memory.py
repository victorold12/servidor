"""/api/memory — grafo de memória de longo prazo (Seção 7 do esquema).

O BACKEND é a fonte única da verdade da memória. O site (e depois extensão e
desktop) leem com GET e escrevem o grafo inteiro com PUT — a lógica de fusão
(dedup, relações funcionais que substituem, poda por teto) roda no cliente e o
resultado é persistido aqui atômico. Assim não existe "conflito de sync": só
há uma verdade, e o cliente mantém só cache descartável.

Single-user por ora: user_id fixo 'victor' (mesmo default de paired_agents).
Multi-usuário é item futuro — a coluna user_id já está pronta pra isso.
"""
import time
from datetime import date, datetime, timezone

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .. import db, embeddings, memory_facts
from ..openrouter import chat, content_of, resolve_key
from ..router_llm import classifier_model
from .catalog import fetch_catalog

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


# =====================================================================
# Extração automática de fatos (Seção 13.1 — absorvido do Leon AI)
# =====================================================================
def _carrega_grafo(conn) -> dict:
    nodes = conn.execute(
        "SELECT node_id AS id, label, type FROM memory_nodes WHERE user_id = ? ORDER BY rowid",
        (_USER,),
    ).fetchall()
    edges = conn.execute(
        "SELECT source, relation, target, confidence FROM memory_edges WHERE user_id = ? ORDER BY id",
        (_USER,),
    ).fetchall()
    return {"nodes": [dict(n) for n in nodes], "edges": [dict(e) for e in edges]}


def _grava_grafo(conn, graph: dict, novos: list[str]) -> None:
    """Regrava o grafo preservando o created_at dos nós que já existiam — a
    camada diária depende dessa data, então sobrescrever tudo com 'agora' faria
    fato velho aparecer no resumo de hoje."""
    antigos = {
        r["node_id"]: r["created_at"]
        for r in conn.execute(
            "SELECT node_id, created_at FROM memory_nodes WHERE user_id = ?", (_USER,))
    }
    agora = time.time()
    conn.execute("DELETE FROM memory_nodes WHERE user_id = ?", (_USER,))
    conn.execute("DELETE FROM memory_edges WHERE user_id = ?", (_USER,))
    conn.executemany(
        "INSERT INTO memory_nodes (user_id, node_id, label, type, created_at) VALUES (?, ?, ?, ?, ?)",
        [(_USER, n["id"], n["label"], n.get("type", "fato"),
          agora if n["id"] in novos else antigos.get(n["id"]))
         for n in graph["nodes"]],
    )
    conn.executemany(
        "INSERT INTO memory_edges (user_id, source, relation, target, confidence) VALUES (?, ?, ?, ?, ?)",
        [(_USER, e["source"], e["relation"], e["target"], e.get("confidence", 0.9))
         for e in graph["edges"]],
    )


async def _modelo_barato(key: str) -> str | None:
    """Extrair fato e resumir dia não devem custar: usa um modelo grátis."""
    try:
        catalogo, _ = await fetch_catalog(key)
    except RuntimeError:
        return None
    return classifier_model(catalogo)


class ExtractIn(BaseModel):
    messages: list[dict]
    model: str | None = None          # força um extrator; senão escolhe um grátis


@router.post("/memory/extract")
async def extract_facts(
    body: ExtractIn,
    x_or_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    """Lê a conversa, extrai fatos duráveis e funde no grafo.

    Devolve exatamente o que mudou. Nenhum fato extraído é resultado válido e
    comum — conversa sobre código raramente diz algo durável sobre o usuário.
    """
    key = resolve_key(x_or_key or authorization)
    modelo = body.model or await _modelo_barato(key)
    if not modelo:
        raise HTTPException(
            status_code=503,
            detail="Sem modelo disponível pra extrair fatos (catálogo indisponível).",
        )

    fatos = await memory_facts.extract(body.messages, key, modelo)
    if not fatos:
        return {"ok": True, "extraidos": 0, "aplicados": {}, "modelo": modelo}

    with db.get_conn() as conn:
        graph = _carrega_grafo(conn)
        mudou = memory_facts.merge(graph, fatos)
        _grava_grafo(conn, graph, mudou["nos_novos"])
        # vetor de nó que saiu não serve mais
        for removido in mudou["nos_removidos"]:
            conn.execute(
                "DELETE FROM memory_vectors WHERE user_id = ? AND kind = 'node' AND ref = ?",
                (_USER, removido))

    await _indexa_nos(mudou["nos_novos"])
    return {"ok": True, "extraidos": len(fatos), "fatos": fatos,
            "aplicados": mudou, "modelo": modelo}


# =====================================================================
# Camada diária (Seção 13.1 — resumo consolidado por dia)
# =====================================================================
def _dia_de(ts: float | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


class DailyIn(BaseModel):
    day: str | None = None            # YYYY-MM-DD; vazio = hoje
    model: str | None = None


@router.post("/memory/daily")
async def build_daily(
    body: DailyIn,
    x_or_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    """Consolida os fatos de um dia num resumo só.

    Existe pra busca não afogar em fato solto: em vez de 30 nós do mesmo dia
    competindo, o dia vira um texto com contexto.
    """
    dia = body.day or date.today().strftime("%Y-%m-%d")
    key = resolve_key(x_or_key or authorization)

    with db.get_conn() as conn:
        linhas = conn.execute(
            "SELECT node_id, label, type, created_at FROM memory_nodes "
            "WHERE user_id = ? AND created_at IS NOT NULL ORDER BY created_at",
            (_USER,),
        ).fetchall()
        arestas = conn.execute(
            "SELECT source, relation, target FROM memory_edges WHERE user_id = ?",
            (_USER,),
        ).fetchall()

    do_dia = [r for r in linhas if _dia_de(r["created_at"]) == dia]
    if not do_dia:
        return {"ok": True, "day": dia, "summary": None,
                "note": "nenhum fato registrado neste dia"}

    rotulo = {r["node_id"]: r["label"] for r in linhas}
    ids_dia = {r["node_id"] for r in do_dia}
    frases = [
        f"{rotulo.get(e['source'], e['source'])} {e['relation']} {rotulo.get(e['target'], e['target'])}"
        for e in arestas
        if e["source"] in ids_dia or e["target"] in ids_dia
    ]
    if not frases:
        frases = [r["label"] for r in do_dia]

    modelo = body.model or await _modelo_barato(key)
    bruto = "; ".join(frases)
    resumo = bruto[:600]
    if modelo:
        try:
            r = await chat(
                [{"role": "user", "content":
                  "Reescreva os fatos abaixo como um parágrafo curto e factual, em "
                  "português, sem inventar nada que não esteja listado e sem "
                  "comentar o processo.\n\n" + bruto}],
                key=key, model=modelo,
            )
            texto = content_of(r).strip()
            if texto:
                resumo = texto[:1200]
        except Exception:  # noqa: BLE001 — sem modelo, a concatenação dos fatos serve
            pass

    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO memory_daily (user_id, day, summary, fact_count, updated_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id, day) DO UPDATE SET "
            "summary = excluded.summary, fact_count = excluded.fact_count, "
            "updated_at = excluded.updated_at",
            (_USER, dia, resumo, len(do_dia), time.time()),
        )

    await _indexa_diario(dia, resumo)
    return {"ok": True, "day": dia, "summary": resumo,
            "fact_count": len(do_dia), "resumido_por": modelo}


@router.get("/memory/daily")
def list_daily(limit: int = 30):
    with db.get_conn() as conn:
        linhas = conn.execute(
            "SELECT day, summary, fact_count, updated_at FROM memory_daily "
            "WHERE user_id = ? ORDER BY day DESC LIMIT ?",
            (_USER, max(1, min(limit, 365))),
        ).fetchall()
    return {"days": [dict(r) for r in linhas]}


# =====================================================================
# Busca na memória (semântica quando há provedor; léxica quando não há)
# =====================================================================
async def _indexa(kind: str, itens: list[tuple[str, str]]) -> None:
    """Guarda o vetor de cada item. Sem provedor, guarda só o texto com o
    marcador léxico — a busca sabe distinguir e não trata um como o outro."""
    if not itens:
        return
    textos = [t for _, t in itens]
    try:
        vetores, modelo = await embeddings.embed(textos)
    except Exception:  # noqa: BLE001 — sem provedor ou provedor fora: fica no léxico
        vetores, modelo = [[] for _ in itens], embeddings.LEXICAL_MODEL

    with db.get_conn() as conn:
        for (ref, texto), vetor in zip(itens, vetores):
            conn.execute(
                "INSERT INTO memory_vectors (user_id, kind, ref, text, dim, vector, model) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(user_id, kind, ref) DO UPDATE SET "
                "text = excluded.text, dim = excluded.dim, vector = excluded.vector, "
                "model = excluded.model",
                (_USER, kind, ref, texto, len(vetor),
                 embeddings.pack(vetor) if vetor else b"", modelo),
            )


async def _indexa_nos(node_ids: list[str]) -> None:
    if not node_ids:
        return
    with db.get_conn() as conn:
        marcas = ",".join("?" for _ in node_ids)
        linhas = conn.execute(
            f"SELECT node_id, label, type FROM memory_nodes "
            f"WHERE user_id = ? AND node_id IN ({marcas})",
            (_USER, *node_ids),
        ).fetchall()
    await _indexa("node", [(r["node_id"], f"{r['label']} ({r['type']})") for r in linhas])


async def _indexa_diario(dia: str, resumo: str) -> None:
    await _indexa("daily", [(dia, resumo)])


@router.post("/memory/reindex")
async def reindex():
    """Recalcula os vetores de tudo. Necessário depois de configurar (ou trocar)
    o provedor de embeddings: vetor de modelo diferente não é comparável.

    Documentos (kind='doc') são REVETORIZADOS a partir do texto já guardado, não
    reenviados pelo usuário: o arquivo original nunca chegou aqui — só o texto
    dele. Sem isto, ligar os embeddings deixaria a memória buscável por
    significado e os documentos presos no léxico, sem nada na tela explicando a
    diferença.
    """
    with db.get_conn() as conn:
        nos = conn.execute(
            "SELECT node_id, label, type FROM memory_nodes WHERE user_id = ?", (_USER,)
        ).fetchall()
        dias = conn.execute(
            "SELECT day, summary FROM memory_daily WHERE user_id = ?", (_USER,)
        ).fetchall()
        pedacos = conn.execute(
            "SELECT ref, text FROM memory_vectors WHERE user_id = ? AND kind = 'doc'", (_USER,)
        ).fetchall()

    await _indexa("node", [(r["node_id"], f"{r['label']} ({r['type']})") for r in nos])
    await _indexa("daily", [(r["day"], r["summary"]) for r in dias])
    await _indexa("doc", [(r["ref"], r["text"]) for r in pedacos])
    return {"ok": True, "nodes": len(nos), "days": len(dias), "doc_chunks": len(pedacos),
            "mode": "semantic" if embeddings.configured() else "lexical"}


@router.get("/memory/search")
async def search_memory(q: str, limit: int = 8):
    """Busca na memória. `mode` diz o que realmente aconteceu:

      semantic → comparou vetores de embedding (acha sinônimo)
      lexical  → comparou termos (não acha sinônimo)

    Sem provedor de embeddings a busca é léxica, e a resposta diz isso. Chamar
    contagem de palavra de busca semântica seria mentir sobre a capacidade.
    """
    q = (q or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Informe o termo em `q`.")
    limit = max(1, min(limit, 50))

    with db.get_conn() as conn:
        linhas = conn.execute(
            "SELECT kind, ref, text, dim, vector, model FROM memory_vectors WHERE user_id = ?",
            (_USER,),
        ).fetchall()

    if not linhas:
        return {"mode": "lexical", "query": q, "results": [],
                "note": "memória vazia ou ainda não indexada (rode /api/memory/reindex)"}

    modo = "lexical"
    aviso = None
    vetor_consulta: list[float] = []
    indexados = [r for r in linhas if r["model"] != embeddings.LEXICAL_MODEL and r["dim"]]

    if embeddings.configured() and indexados:
        try:
            vetores, modelo = await embeddings.embed([q])
            vetor_consulta = vetores[0]
            # só compara com vetores do MESMO modelo — dimensões e espaço diferem
            comparaveis = [r for r in indexados if r["model"] == modelo]
            if comparaveis:
                modo = "semantic"
                indexados = comparaveis
            else:
                aviso = ("os vetores guardados são de outro modelo de embedding; "
                         "rode /api/memory/reindex pra comparar de verdade")
        except Exception as exc:  # noqa: BLE001
            aviso = f"provedor de embeddings falhou ({exc}); busca caiu no léxico"
    elif embeddings.configured():
        aviso = "nada indexado com embeddings ainda; rode /api/memory/reindex"

    if modo == "semantic":
        pontuados = [
            (embeddings.cosine(vetor_consulta, embeddings.unpack(r["vector"])), r)
            for r in indexados
        ]
    else:
        pontuados = [(embeddings.lexical_score(q, r["text"]), r) for r in linhas]

    pontuados = [(s, r) for s, r in pontuados if s > 0]
    pontuados.sort(key=lambda t: t[0], reverse=True)

    melhores = pontuados[:limit]

    # Nome do documento de origem, quando o resultado veio de um. Sem isto o
    # modelo recebe um trecho e uma ref opaca ("a3f9c2#7") e não tem como citar
    # a fonte — e resposta de RAG sem fonte é indistinguível de alucinação
    # justamente quando ela acerta.
    nomes: dict[str, str] = {}
    docs = {r["ref"].split("#", 1)[0] for _, r in melhores if r["kind"] == "doc"}
    if docs:
        marcas = ",".join("?" for _ in docs)
        with db.get_conn() as conn:
            nomes = {
                l["doc_id"]: l["name"]
                for l in conn.execute(
                    f"SELECT doc_id, name FROM documents WHERE user_id = ? "
                    f"AND doc_id IN ({marcas})", (_USER, *docs))
            }

    def _item(s, r):
        d = {"kind": r["kind"], "ref": r["ref"], "text": r["text"], "score": round(s, 4)}
        if r["kind"] == "doc":
            d["source"] = nomes.get(r["ref"].split("#", 1)[0], "documento removido")
        return d

    corpo = {
        "mode": modo,
        "query": q,
        "results": [_item(s, r) for s, r in melhores],
    }
    if aviso:
        corpo["warning"] = aviso
    if modo == "lexical" and not embeddings.configured():
        corpo["note"] = ("busca por termos — configure EMBEDDINGS_BASE e "
                         "EMBEDDINGS_MODEL pra busca semântica de verdade")
    return corpo
