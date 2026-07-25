"""Extração automática de fatos da conversa para o grafo de memória.

Absorvido do Leon AI (Seção 13.1 do prompt mestre): em vez de o usuário curar a
memória à mão, um modelo lê a conversa e devolve os fatos como triplas
(sujeito → relação → objeto), que entram como nó e aresta.

As regras de fusão são as mesmas que o painel já usava
(VTz-painel/src/js/05-memory-graph-merge.js), trazidas pra cá:

  - id de nó é derivado do rótulo (slug), então o mesmo fato dito duas vezes
    de formas parecidas cai no mesmo nó em vez de duplicar;
  - relação FUNCIONAL (mora em, trabalha como…) SUBSTITUI o alvo anterior — é
    assim que o grafo corrige contradição em vez de acumular as duas versões;
  - nó que ficou órfão depois de uma substituição é removido;
  - teto de nós, com os mais antigos saindo primeiro.

Quem extrai é um modelo grátis do catálogo: memória não deve custar por
conversa.
"""
import json
import re
import unicodedata

from .openrouter import chat, content_of

# Relações onde só UM alvo faz sentido. Dizer "moro em Belém" depois de
# "moro em Ananindeua" é correção, não uma segunda cidade.
FUNCTIONAL = {
    "mora em", "nasceu em", "trabalha como", "se chama", "tem idade",
    "estuda em", "usa como principal",
}

NODE_TYPES = ["pessoa", "lugar", "projeto", "preferencia", "fato", "organizacao"]

MAX_NODES = 120          # mesmo teto do painel
_MAX_FATOS_POR_VEZ = 12


def slug(label: str) -> str:
    """id determinístico a partir do rótulo — é o que faz o dedup funcionar."""
    txt = unicodedata.normalize("NFKD", str(label).lower().strip())
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    txt = re.sub(r"[^a-z0-9]+", "-", txt).strip("-")
    return txt[:60] or "no"


def upsert_node(graph: dict, label: str, tipo: str) -> str:
    node_id = slug(label)
    for n in graph["nodes"]:
        if n["id"] == node_id:
            # tipo mais específico promove o genérico "fato"
            if tipo and n.get("type") == "fato" and tipo != "fato":
                n["type"] = tipo
            return node_id
    graph["nodes"].append({
        "id": node_id,
        "label": str(label)[:80],
        "type": tipo if tipo in NODE_TYPES else "fato",
    })
    return node_id


def upsert_edge(graph: dict, src: str, relation: str, tgt: str) -> None:
    relation = str(relation).lower().strip()[:40]
    if src == tgt:
        return

    if relation in FUNCTIONAL:
        antigas = [e for e in graph["edges"]
                   if e["source"] == src and e["relation"] == relation and e["target"] != tgt]
        graph["edges"] = [e for e in graph["edges"]
                          if not (e["source"] == src and e["relation"] == relation
                                  and e["target"] != tgt)]
        # o alvo substituído só é apagado se ninguém mais aponta pra ele
        for velha in antigas:
            alvo = velha["target"]
            if not any(e["source"] == alvo or e["target"] == alvo for e in graph["edges"]):
                graph["nodes"] = [n for n in graph["nodes"] if n["id"] != alvo]

    if any(e["source"] == src and e["relation"] == relation and e["target"] == tgt
           for e in graph["edges"]):
        return
    graph["edges"].append({"source": src, "relation": relation,
                           "target": tgt, "confidence": 0.9})


def prune(graph: dict) -> None:
    """Corta os nós mais antigos acima do teto e as arestas que ficaram soltas."""
    excesso = len(graph["nodes"]) - MAX_NODES
    if excesso <= 0:
        return
    removidos = {n["id"] for n in graph["nodes"][:excesso]}
    graph["nodes"] = graph["nodes"][excesso:]
    graph["edges"] = [e for e in graph["edges"]
                      if e["source"] not in removidos and e["target"] not in removidos]


_PROMPT = (
    "Extraia da conversa apenas FATOS DURÁVEIS sobre o usuário — coisas que "
    "continuam verdade depois que a conversa acaba (nome, onde mora, trabalho, "
    "projetos, preferências fortes, pessoas próximas).\n\n"
    "NÃO extraia: o que ele pediu agora, dúvidas, conteúdo que o assistente "
    "gerou, nem nada dito de forma hipotética.\n\n"
    "Responda APENAS com JSON:\n"
    '{"fatos":[{"sujeito":"...","tipo_sujeito":"pessoa|lugar|projeto|preferencia|organizacao|fato",'
    '"relacao":"...","objeto":"...","tipo_objeto":"pessoa|lugar|projeto|preferencia|organizacao|fato"}]}\n\n'
    f"No máximo {_MAX_FATOS_POR_VEZ} fatos. Se não houver fato durável, responda "
    '{"fatos":[]} — lista vazia é resposta válida e melhor que inventar.\n\n'
    "Relações que aceitam UM único valor (use exatamente estes termos quando "
    "couber): " + ", ".join(sorted(FUNCTIONAL))
)


def _conversa_em_texto(messages: list[dict], limite: int = 6000) -> str:
    partes = []
    for m in messages:
        papel = m.get("role")
        if papel not in ("user", "assistant"):
            continue
        conteudo = m.get("content")
        if not isinstance(conteudo, str) or not conteudo.strip():
            continue
        partes.append(f"{'Usuário' if papel == 'user' else 'Assistente'}: {conteudo}")
    return "\n".join(partes)[-limite:]


async def extract(messages: list[dict], key: str, model: str) -> list[dict]:
    """Devolve a lista de triplas que o modelo achou. Lista vazia é resultado
    legítimo. Falha do extrator devolve vazio — memória é melhor-esforço e nunca
    deve derrubar a conversa."""
    texto = _conversa_em_texto(messages)
    if not texto.strip():
        return []
    try:
        resposta = await chat(
            [{"role": "system", "content": _PROMPT},
             {"role": "user", "content": texto}],
            key=key, model=model,
        )
        cru = content_of(resposta).replace("```json", "").replace("```", "").strip()
        fatos = json.loads(cru).get("fatos") or []
    except Exception:  # noqa: BLE001 — extrator é best-effort
        return []

    validos = []
    for f in fatos[:_MAX_FATOS_POR_VEZ]:
        if not isinstance(f, dict):
            continue
        s, r, o = f.get("sujeito"), f.get("relacao"), f.get("objeto")
        if not (isinstance(s, str) and isinstance(r, str) and isinstance(o, str)):
            continue
        if not (s.strip() and r.strip() and o.strip()):
            continue
        validos.append({
            "sujeito": s.strip(), "relacao": r.strip(), "objeto": o.strip(),
            "tipo_sujeito": f.get("tipo_sujeito") or "fato",
            "tipo_objeto": f.get("tipo_objeto") or "fato",
        })
    return validos


def merge(graph: dict, fatos: list[dict]) -> dict:
    """Aplica as triplas no grafo. Devolve o que mudou, pra quem chamou poder
    contar honestamente (e pra saber quais nós precisam de vetor novo)."""
    antes_nos = {n["id"] for n in graph["nodes"]}
    antes_arestas = {(e["source"], e["relation"], e["target"]) for e in graph["edges"]}

    for f in fatos:
        sid = upsert_node(graph, f["sujeito"], f["tipo_sujeito"])
        tid = upsert_node(graph, f["objeto"], f["tipo_objeto"])
        upsert_edge(graph, sid, f["relacao"], tid)

    prune(graph)

    agora_nos = {n["id"] for n in graph["nodes"]}
    agora_arestas = {(e["source"], e["relation"], e["target"]) for e in graph["edges"]}
    return {
        "nos_novos": sorted(agora_nos - antes_nos),
        "nos_removidos": sorted(antes_nos - agora_nos),
        "arestas_novas": len(agora_arestas - antes_arestas),
        "arestas_removidas": len(antes_arestas - agora_arestas),
    }
