"""/api/analytics — "o que o JARVIS mais fez essa semana" (Seção 5 do prompt mestre).

Nada de coleta nova: o dado já existe no log de auditoria, que foi criado pela
Seção 8 (segurança). Isto aqui só agrega o que já está gravado — é exatamente o
que o PDF previu ao dizer "dado que já é coletado, só falta um painel".

Duas honestidades embutidas:

  - a janela é declarada na resposta (`from_ts`/`days`), pra ninguém ler "47
    ações" sem saber de quanto tempo;
  - `chain_ok` diz se a cadeia de hash da auditoria fecha. Se alguém adulterou
    o log, o número agregado em cima dele não é confiável, e o painel precisa
    saber disso em vez de exibir estatística bonita sobre dado corrompido.
"""
import time

from fastapi import APIRouter

from .. import telemetria

from .. import db
from .agents_hub import verify_audit_chain

router = APIRouter()

# Rótulo legível por tipo de ação. Ação desconhecida aparece com o próprio nome
# em vez de virar "outros" — melhor mostrar algo estranho do que esconder.
_LABEL = {
    "fs_read": "Ler arquivo",
    "fs_write": "Gravar arquivo",
    "fs_list": "Listar pasta",
    "fs_mkdir": "Criar pasta",
    "fs_delete": "Apagar",
    "run": "Executar programa",
}

_TIER_LABEL = {1: "automático", 2: "confirmado", 3: "fora do padrão", 4: "bloqueado"}


@router.get("/analytics")
def usage(days: int = 7):
    """Agrega o log de auditoria numa visão de uso.

    `days` é a janela em dias (1 a 365). Devolve totais, quebra por ação, por
    tier, por decisão, os alvos mais tocados e a atividade por dia.
    """
    days = max(1, min(days, 365))
    desde = time.time() - days * 86400

    with db.get_conn() as conn:
        linhas = conn.execute(
            "SELECT action_type, target, tier, decision, result, ts, agent_id "
            "FROM audit_log WHERE ts >= ? ORDER BY ts",
            (desde,),
        ).fetchall()
        integridade = verify_audit_chain(conn)

    total = len(linhas)
    por_acao: dict[str, int] = {}
    por_tier: dict[int, int] = {}
    por_decisao: dict[str, int] = {}
    por_resultado: dict[str, int] = {}
    por_dia: dict[str, int] = {}
    por_agente: dict[str, int] = {}
    alvos: dict[str, int] = {}

    for r in linhas:
        por_acao[r["action_type"]] = por_acao.get(r["action_type"], 0) + 1
        por_tier[r["tier"]] = por_tier.get(r["tier"], 0) + 1
        por_decisao[r["decision"]] = por_decisao.get(r["decision"], 0) + 1
        por_resultado[r["result"]] = por_resultado.get(r["result"], 0) + 1
        por_agente[r["agent_id"]] = por_agente.get(r["agent_id"], 0) + 1
        dia = time.strftime("%Y-%m-%d", time.gmtime(r["ts"]))
        por_dia[dia] = por_dia.get(dia, 0) + 1
        if r["target"]:
            alvos[r["target"]] = alvos.get(r["target"], 0) + 1

    def ranking(d: dict, n: int = 10) -> list[dict]:
        return [{"nome": k, "total": v}
                for k, v in sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:n]]

    negadas = sum(v for k, v in por_decisao.items() if k in ("deny", "denied", "negado"))

    corpo = {
        "days": days,
        "from_ts": desde,
        "total": total,
        "acoes": [
            {"tipo": k, "label": _LABEL.get(k, k), "total": v}
            for k, v in sorted(por_acao.items(), key=lambda kv: kv[1], reverse=True)
        ],
        "tiers": [
            {"tier": k, "label": _TIER_LABEL.get(k, f"tier {k}"), "total": v}
            for k, v in sorted(por_tier.items())
        ],
        "decisoes": ranking(por_decisao),
        "resultados": ranking(por_resultado),
        "alvos_mais_tocados": ranking(alvos),
        "agentes": ranking(por_agente),
        "por_dia": [{"dia": k, "total": v} for k, v in sorted(por_dia.items())],
        "negadas": negadas,
        # se a cadeia não fecha, o agregado acima está em cima de log adulterado
        "chain_ok": bool(integridade.get("ok")),
    }
    if not integridade.get("ok"):
        corpo["chain_warning"] = (
            "A cadeia de hash da auditoria não fecha — o log foi alterado fora do "
            "sistema. Trate estes números como não confiáveis e veja /api/audit/verify."
        )
    if total == 0:
        corpo["note"] = f"nenhuma ação registrada nos últimos {days} dia(s)"
    return corpo


@router.get("/analytics/custo")
def custo(days: int = 7):
    """Para onde foram os R$ 50 — gasto de MODELO, não ações no PC.

    Endpoint separado do /analytics de propósito. Os dois medem coisas
    diferentes de fontes diferentes: aquele agrega a auditoria (o que o JARVIS
    fez na máquina), este agrega as chamadas a modelo. Juntar num só forçaria a
    escolher uma janela e uma unidade para dois fenômenos que não compartilham
    nenhuma das duas — e o número resultante não responderia bem a nenhuma das
    duas perguntas.

    `custo_e_estimativa: true` vai na resposta e não é formalidade: o preço por
    token vem do catálogo do OpenRouter e muda, inclusive por promoção. Quem
    exibir isso precisa dizer que é estimativa, senão vira número que mente com
    confiança — e decisão de orçamento seria tomada em cima dele.
    """
    return telemetria.resumo(dias=max(1, min(int(days or 7), 90)))


@router.post("/analytics/custo")
def registra_custo(lote: dict):
    """Recebe chamadas medidas pelo PAINEL.

    Existe porque o painel fala com o OpenRouter DIRETO (OR_BASE em
    00-core-state.js) — o backend só vê agentes, orquestração e RAG. Instrumentar
    apenas o backend mediria a minoria do gasto, e um número parcial que se
    apresenta como total é pior que número nenhum: decisões de orçamento seriam
    tomadas em cima dele.

    Em lote porque o painel acumula e descarrega: uma requisição por chamada de
    modelo dobraria o tráfego pra medir tráfego.

    Nada aqui confia no cliente além do que já é dele: são as próprias métricas
    do usuário, sobre a própria chave. O teto de 500 evita que um laço no
    navegador encha o banco.
    """
    itens = (lote or {}).get("chamadas") or []
    if not isinstance(itens, list):
        return {"ok": False, "erro": "esperava {chamadas: [...]}"}

    gravadas = 0
    for c in itens[:500]:
        if not isinstance(c, dict):
            continue
        telemetria.registra(
            provider=str(c.get("provider") or "openrouter")[:40],
            model=str(c.get("model") or "?")[:120],
            origem=str(c.get("origem") or "painel")[:40],
            tokens_in=c.get("tokens_in") if isinstance(c.get("tokens_in"), int) else None,
            tokens_out=c.get("tokens_out") if isinstance(c.get("tokens_out"), int) else None,
            custo_usd=c.get("custo_usd") if isinstance(c.get("custo_usd"), (int, float)) else None,
            ms=c.get("ms") if isinstance(c.get("ms"), int) else None,
            ok=bool(c.get("ok", True)),
            erro=(str(c["erro"])[:200] if c.get("erro") else None),
        )
        gravadas += 1
    return {"ok": True, "gravadas": gravadas, "recebidas": len(itens)}
