"""Vetores para busca na memória.

O prompt mestre (Seção 2) pede "busca semântica de verdade (embeddings, não
contagem de palavra)". Semântica de verdade exige um modelo de embedding, e o
OpenRouter não serve embeddings — então isto fala com um endpoint compatível com
a API da OpenAI (`POST /embeddings`), que é o que praticamente todos expõem:
OpenAI, HuggingFace TEI, Ollama, LM Studio, vLLM.

Configuração (.env):
    EMBEDDINGS_BASE   ex.: https://api.openai.com/v1  ou  http://localhost:11434/v1
    EMBEDDINGS_MODEL  ex.: text-embedding-3-small  ou  nomic-embed-text
    EMBEDDINGS_KEY    opcional (endpoint local costuma não pedir)

Sem provedor configurado, a busca NÃO finge ser semântica: cai num escore
léxico e a resposta declara `mode: "lexical"`. Chamar contagem de palavra de
"busca semântica" seria mentir pro usuário sobre o que ele tem.
"""
import math
import re
import struct
import unicodedata

import httpx

from .config import settings

LEXICAL_MODEL = "lexico"          # marcador de "não é vetor de embedding"


def configured() -> bool:
    return bool(getattr(settings, "embeddings_base", "") and
                getattr(settings, "embeddings_model", ""))


def pack(vector: list[float]) -> bytes:
    """float32 em sequência — compacto e sem virar JSON opaco no banco."""
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


async def embed(texts: list[str]) -> tuple[list[list[float]], str]:
    """Devolve (vetores, modelo). Levanta se o provedor está configurado mas
    falhou — quem chama decide cair no léxico, mas sabendo que caiu."""
    if not texts:
        return [], settings.embeddings_model
    if not configured():
        raise RuntimeError("nenhum provedor de embeddings configurado")

    headers = {"Content-Type": "application/json"}
    if getattr(settings, "embeddings_key", ""):
        headers["Authorization"] = f"Bearer {settings.embeddings_key}"

    base = settings.embeddings_base.rstrip("/")
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        resp = await client.post(
            f"{base}/embeddings",
            json={"model": settings.embeddings_model, "input": texts},
            headers=headers,
        )
        resp.raise_for_status()
        dados = resp.json().get("data") or []

    vetores = [d.get("embedding") for d in dados]
    if len(vetores) != len(texts) or any(not v for v in vetores):
        raise RuntimeError("provedor de embeddings devolveu resposta incompleta")
    return vetores, settings.embeddings_model


# ---------------------------------------------------------------- léxico
_STOP = {
    "de", "da", "do", "das", "dos", "e", "o", "a", "os", "as", "um", "uma",
    "em", "no", "na", "nos", "nas", "que", "com", "por", "para", "pra", "se",
    "meu", "minha", "seu", "sua", "ele", "ela", "eu", "the", "of", "to", "is",
}


def tokens(texto: str) -> list[str]:
    txt = unicodedata.normalize("NFKD", str(texto).lower())
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return [t for t in re.findall(r"[a-z0-9]+", txt) if len(t) > 2 and t not in _STOP]


def lexical_score(consulta: str, texto: str) -> float:
    """Sobreposição de termos (Jaccard com peso na consulta). Não é semântica —
    "cachorro" não acha "cão" aqui. É o que dá pra fazer sem modelo."""
    a, b = set(tokens(consulta)), set(tokens(texto))
    if not a or not b:
        return 0.0
    comuns = a & b
    if not comuns:
        # prefixo ajuda em plural/flexão ("projeto" x "projetos")
        for ta in a:
            if any(tb.startswith(ta[:4]) or ta.startswith(tb[:4]) for tb in b):
                return 0.15
        return 0.0
    return len(comuns) / len(a | b) + 0.3 * (len(comuns) / len(a))
