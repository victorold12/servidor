"""Telemetria de chamadas a modelo — para onde vão os R$ 50/mês.

O orçamento deste projeto é R$ 50/mês no OpenRouter, e até aqui não havia como
saber onde eles eram gastos. O `/api/analytics` agrega a auditoria — o que o
JARVIS fez no PC — e isso não diz nada sobre modelo.

DUAS REGRAS QUE DEFINEM ESTE MÓDULO

1. Falha de telemetria NUNCA derruba a chamada que ela mede. Toda função aqui
   engole a própria exceção. Observabilidade que causa indisponibilidade é o
   oposto do objetivo, e um `except` mal colocado aqui transformaria "não
   consegui gravar a métrica" em "sua pergunta falhou".

2. Custo é ESTIMATIVA e é dito como tal. O preço por token vem do catálogo do
   OpenRouter e muda — inclusive por promoção. Um número que se apresenta como
   fatura real e diverge dela é pior que nenhum número, porque decisões são
   tomadas em cima dele. `custo_usd` é NULL quando não deu pra estimar, e nunca
   0: zero significa "foi de graça" (o caso do Ollama), que é informação
   diferente de "não sei".
"""
import time

import httpx

from .config import settings
from .db import get_conn

# Preço por token, por modelo, como o OpenRouter informa. Cacheado em memória:
# a lista tem centenas de modelos e não muda de minuto a minuto. Some no
# restart, que no Render acontece com frequência — e tudo bem, é só re-buscar.
_precos: dict[str, tuple[float, float]] = {}
_precos_em: float = 0.0
_PRECOS_TTL = 6 * 3600


async def _carrega_precos() -> dict[str, tuple[float, float]]:
    """Busca preços do catálogo. Falha aqui não é erro: sem preço a chamada
    continua sendo registrada, só sem estimativa de custo."""
    global _precos, _precos_em
    if _precos and (time.time() - _precos_em) < _PRECOS_TTL:
        return _precos
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{settings.openrouter_base}/models")
            r.raise_for_status()
            novo = {}
            for m in (r.json().get("data") or []):
                p = m.get("pricing") or {}
                try:
                    novo[m["id"]] = (float(p.get("prompt") or 0), float(p.get("completion") or 0))
                except (TypeError, ValueError):
                    continue
            if novo:
                _precos, _precos_em = novo, time.time()
    except Exception:
        pass
    return _precos


async def aquece_precos() -> None:
    """Garante que os preços estão em memória. Chamado na ENTRADA do streaming,
    onde `await` é seguro — dentro de `finally` de gerador assíncrono não é: se
    o cliente desconecta no meio, o gerador recebe GeneratorExit e um `await`
    ali levanta RuntimeError. O painel cancela streaming o tempo todo (usuário
    manda outra pergunta antes de terminar), então isso não é hipótese."""
    await _carrega_precos()


def estima_custo_cache(model: str, tokens_in: int | None, tokens_out: int | None) -> float | None:
    """Versão síncrona, só com o que já está em memória. Usada onde não dá pra
    esperar. Cache frio devolve None — que é honesto: "não sei" e não "zero"."""
    if tokens_in is None and tokens_out is None:
        return None
    par = _precos.get(model)
    if not par:
        return None
    p_in, p_out = par
    return (tokens_in or 0) * p_in + (tokens_out or 0) * p_out


async def estima_custo(model: str, tokens_in: int | None, tokens_out: int | None) -> float | None:
    """Custo em dólares, ou None se não der pra saber.

    O Ollama devolve 0.0 e não None de propósito: rodar local É de graça, e
    isso é um fato — enquanto "não achei o preço deste modelo" é ignorância.
    Misturar os dois esconderia justamente a economia que o local traz.
    """
    if tokens_in is None and tokens_out is None:
        return None
    precos = await _carrega_precos()
    par = precos.get(model)
    if not par:
        return None
    p_in, p_out = par
    return (tokens_in or 0) * p_in + (tokens_out or 0) * p_out


def registra(*, provider: str, model: str, origem: str,
             tokens_in: int | None = None, tokens_out: int | None = None,
             custo_usd: float | None = None, ms: int | None = None,
             ok: bool = True, erro: str | None = None) -> None:
    """Grava uma chamada. Engole a própria exceção — ver regra 1 do módulo."""
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO llm_calls (ts, provider, model, origem, tokens_in,"
                " tokens_out, custo_usd, ms, ok, erro)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (time.time(), provider, model, origem, tokens_in, tokens_out,
                 custo_usd, ms, 1 if ok else 0, (erro or None)),
            )
    except Exception:
        pass


def uso_de(data: dict) -> tuple[int | None, int | None]:
    """Extrai tokens do formato OpenAI, tolerando ausência.

    Nem todo provedor devolve `usage`, e alguns só devolvem no fim do
    streaming. Ausência é normal e vira None — não zero, que mentiria dizendo
    que a chamada não consumiu nada.
    """
    u = (data or {}).get("usage") or {}
    ent = u.get("prompt_tokens")
    sai = u.get("completion_tokens")
    return (ent if isinstance(ent, int) else None,
            sai if isinstance(sai, int) else None)


def resumo(dias: int = 7) -> dict:
    """Agregado para o painel. A janela vai NA RESPOSTA, seguindo o que o
    /api/analytics já faz: ninguém deve ler "R$ 12" sem saber de quanto tempo."""
    desde = time.time() - dias * 86400
    try:
        with get_conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) c, COALESCE(SUM(custo_usd),0) usd,"
                " COALESCE(SUM(tokens_in),0) ti, COALESCE(SUM(tokens_out),0) to_,"
                " COALESCE(AVG(ms),0) ms, SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END) falhas"
                " FROM llm_calls WHERE ts >= ?", (desde,)).fetchone()
            por_modelo = conn.execute(
                "SELECT model, provider, COUNT(*) c, COALESCE(SUM(custo_usd),0) usd,"
                " COALESCE(AVG(ms),0) ms FROM llm_calls WHERE ts >= ?"
                " GROUP BY model, provider ORDER BY usd DESC, c DESC LIMIT 25", (desde,)).fetchall()
            por_origem = conn.execute(
                "SELECT origem, COUNT(*) c, COALESCE(SUM(custo_usd),0) usd"
                " FROM llm_calls WHERE ts >= ? GROUP BY origem ORDER BY usd DESC", (desde,)).fetchall()
            por_dia = conn.execute(
                "SELECT CAST(ts/86400 AS INTEGER) d, COUNT(*) c,"
                " COALESCE(SUM(custo_usd),0) usd FROM llm_calls WHERE ts >= ?"
                " GROUP BY d ORDER BY d", (desde,)).fetchall()
    except Exception as e:
        return {"ok": False, "erro": str(e)[:200], "dias": dias}

    return {
        "ok": True,
        "dias": dias,
        "desde_ts": desde,
        "custo_e_estimativa": True,   # ver regra 2 do módulo
        "total": {
            "chamadas": total["c"], "custo_usd": round(total["usd"], 6),
            "tokens_in": total["ti"], "tokens_out": total["to_"],
            "ms_medio": round(total["ms"]), "falhas": total["falhas"] or 0,
        },
        "por_modelo": [
            {"model": r["model"], "provider": r["provider"], "chamadas": r["c"],
             "custo_usd": round(r["usd"], 6), "ms_medio": round(r["ms"])}
            for r in por_modelo
        ],
        "por_origem": [
            {"origem": r["origem"], "chamadas": r["c"], "custo_usd": round(r["usd"], 6)}
            for r in por_origem
        ],
        "por_dia": [
            {"dia_epoch": r["d"], "chamadas": r["c"], "custo_usd": round(r["usd"], 6)}
            for r in por_dia
        ],
    }
