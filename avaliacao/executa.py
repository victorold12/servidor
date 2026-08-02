"""O corredor. Roda os casos, julga, e grava a execução pra poder comparar.

===========================================================================
POR QUE ELE É GRÁTIS POR PADRÃO

Um arnês que cobra pra rodar não é rodado. Com R$ 50/mês de orçamento, uma
suíte que gasta US$ 0,30 por execução seria consultada uma vez por semana — e
arnês consultado uma vez por semana não pega regressão, pega arqueologia.

Dois alvos (`roteamento` e `fala`) não chamam modelo nenhum: são decisão e
transformação de texto, verificáveis de graça e em milissegundos. O terceiro
(`resposta`) chama, e por padrão vai pro modelo LOCAL — que existe desde que o
gerente de residência foi ligado. A nuvem é opt-in e o custo estimado é impresso
ANTES de gastar.

===========================================================================
POR QUE EXERCITA O CAMINHO REAL

`roteamento` chama `app.complexidade.decide`. `fala` roda o `fala-natural.js`
DE VERDADE, por subprocesso — não uma reimplementação em Python, que passaria a
medir a cópia em vez do produto. `resposta` passa por `app.openrouter.chat`, o
mesmo ponto que o backend usa (e de quebra exercita a telemetria).

Reimplementar o que se mede é o jeito mais confortável de ter um arnês sempre
verde.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from avaliacao import scorers                       # noqa: E402
from avaliacao.casos import carrega, Caso           # noqa: E402

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parent
PASTA_EXECUCOES = AQUI / "execucoes"
NODE_FALA = RAIZ / "agente-local" / "src" / "fala-natural.js"


# ---------------------------------------------------------------------------
# Executores — um por alvo

def _roda_roteamento(caso: Caso, _cfg) -> tuple[str, dict]:
    from app.complexidade import decide
    ctx = dict(caso.contexto)
    t0 = time.monotonic()
    d = decide(
        caso.entrada,
        historico=int(ctx.get("historico", 0)),
        tem_ferramentas=bool(ctx.get("tem_ferramentas", False)),
        tem_local=bool(ctx.get("tem_local", False)),
        saldo_usd=ctx.get("saldo_usd"),
        critico=bool(ctx.get("critico", False)),
    )
    return d["motivo"], {
        "engine": d["engine"], "desempatar": d["desempatar"], "pontos": d["pontos"],
        "ms": int((time.monotonic() - t0) * 1000), "custo_usd": 0.0,
    }


def _roda_fala(caso: Caso, _cfg) -> tuple[str, dict]:
    """Roda o módulo Node de verdade.

    O texto vai e volta por JSON no stdin/stdout: passar como argumento de linha
    de comando quebraria em quebra de linha, aspas e emoji — que é exatamente o
    que estes casos contêm.
    """
    if not NODE_FALA.exists():
        # Ausência do módulo não pode virar aprovação. Ver scorers.py.
        raise RuntimeError(f"fala-natural.js não encontrado em {NODE_FALA}")
    programa = (
        "let e='';process.stdin.on('data',c=>e+=c).on('end',async()=>{"
        f"const m=await import({json.dumps(NODE_FALA.as_uri())});"
        "process.stdout.write(JSON.stringify(m.paraFala(JSON.parse(e))));});"
    )
    t0 = time.monotonic()
    r = subprocess.run([_node(), "-e", programa],
                       input=json.dumps(caso.entrada), capture_output=True,
                       text=True, encoding="utf-8", timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"node falhou: {(r.stderr or '').strip()[:200]}")
    return json.loads(r.stdout), {"ms": int((time.monotonic() - t0) * 1000), "custo_usd": 0.0}


def _node() -> str:
    return os.environ.get("JARVIS_NODE") or "node"


def _roda_resposta(caso: Caso, cfg) -> tuple[str, dict]:
    import asyncio

    from app import telemetria
    from app.config import settings
    from app.openrouter import chat, content_of

    t0 = time.monotonic()
    dados = asyncio.run(chat(
        [{"role": "user", "content": caso.entrada}],
        key=cfg.chave, model=cfg.modelo or None,
        origem="avaliacao", engine=cfg.engine,
        # SEM CACHE, sempre. O arnês existe pra medir o modelo; medindo o cache
        # ele mediria a si mesmo. A segunda execução acertaria tudo em 0ms e
        # esconderia justamente a regressão que ele deveria achar.
        cache=False,
        # TEMPERATURA ZERO, e isto não é detalhe.
        #
        # A primeira comparação deste arnês acusou duas regressões: uma que eu
        # tinha plantado e outra que não. A segunda era o 3B respondendo
        # diferente entre duas execuções da MESMA versão do código. Regressão
        # falsa é o pior defeito possível num detector de regressão — some com
        # a confiança e faz o relatório ser ignorado, que é como um arnês morre.
        #
        # Zero não elimina a variação (amostragem, empate entre tokens,
        # diferença de lote no servidor), mas derruba a ordem de grandeza. O que
        # sobra é tratado no compara.py, que marca alvo estocástico em vez de
        # afirmar quebra.
        extra={"temperature": 0},
    ))
    ms = int((time.monotonic() - t0) * 1000)
    prov = dados.get("_provider", "?")
    ent, sai = telemetria.uso_de(dados)
    if prov == "ollama":
        custo = 0.0                       # local é de graça DE VERDADE: 0.0, não None
    else:
        mdl = cfg.modelo or settings.default_model
        custo = asyncio.run(telemetria.estima_custo(mdl, ent, sai))
    return content_of(dados), {
        "ms": ms, "custo_usd": custo, "engine": prov,
        "tokens_in": ent, "tokens_out": sai,
    }


EXECUTORES = {
    "roteamento": _roda_roteamento,
    "fala": _roda_fala,
    "resposta": _roda_resposta,
}


# ---------------------------------------------------------------------------

def _git_curto() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ,
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or "?"
    except Exception:
        return "?"


def _prepara_local(cfg) -> None:
    """Aponta o backend pro Ollama desta máquina.

    Fica AQUI e não no .env de propósito: no Render, `ollama_base` tem que
    continuar vazio — o container não alcança o 127.0.0.1 do PC do Victor, e
    apontar pra lá faria toda chamada tentar um endereço morto antes de cair na
    nuvem.
    """
    from app.config import settings
    if cfg.engine != "ollama":
        return
    if not settings.ollama_base:
        settings.ollama_base = os.environ.get("OLLAMA_BASE", "http://127.0.0.1:11434/v1")
    if not settings.ollama_model:
        settings.ollama_model = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")


def executa(casos: list[Caso], cfg) -> dict:
    _prepara_local(cfg)
    resultados = []

    for caso in casos:
        executor = EXECUTORES[caso.alvo]
        try:
            saida, meta = executor(caso, cfg)
            erro = None
        except Exception as e:
            # Falha de EXECUÇÃO não é falha do caso: o caso não foi julgado.
            # Marcar como reprovado misturaria "o sistema está errado" com "não
            # consegui perguntar", e as duas pedem ações opostas.
            saida, meta, erro = "", {}, f"{type(e).__name__}: {str(e)[:160]}"

        if erro:
            notas = [scorers.Nota(None, erro, criterio="execucao")]
        else:
            notas = [scorers.aplica(c, saida, meta=meta, entrada=caso.entrada,
                                    julgador=cfg.julgador)
                     for c in caso.criterios]

        resultados.append({
            "id": caso.id, "alvo": caso.alvo, "etiquetas": caso.etiquetas,
            "passou": scorers.veredito(notas),
            "notas": [{"criterio": n.criterio, "passou": n.passou, "detalhe": n.detalhe}
                      for n in notas],
            "ms": meta.get("ms"), "custo_usd": meta.get("custo_usd"),
            "engine": meta.get("engine"),
            "saida": str(saida)[:600],
            "erro": erro,
        })

    passaram = sum(1 for r in resultados if r["passou"] is True)
    falharam = sum(1 for r in resultados if r["passou"] is False)
    indefinidos = sum(1 for r in resultados if r["passou"] is None)

    return {
        "quando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git": _git_curto(),
        "engine": cfg.engine,
        "modelo": cfg.modelo or "",
        "resultados": resultados,
        "resumo": {
            "total": len(resultados), "passaram": passaram,
            "falharam": falharam, "indefinidos": indefinidos,
            "custo_usd": round(sum(r.get("custo_usd") or 0 for r in resultados), 6),
            "ms": sum(r.get("ms") or 0 for r in resultados),
        },
    }


def imprime(exec_: dict, verboso: bool) -> None:
    for r in exec_["resultados"]:
        marca = {True: "  ok  ", False: "FALHA ", None: " ???  "}[r["passou"]]
        print(f"{marca} {r['id']:<28} {r['alvo']:<11} {r['ms'] or 0:>6}ms")
        if r["passou"] is not True or verboso:
            for n in r["notas"]:
                if n["passou"] is not True or verboso:
                    sinal = {True: "ok", False: "não", None: "???"}[n["passou"]]
                    print(f"          [{sinal}] {n['criterio']}: {n['detalhe']}")
            if r["saida"] and r["passou"] is not True:
                print(f"          saída: {r['saida'][:200]!r}")

    s = exec_["resumo"]
    print(f"\n{s['passaram']} passaram, {s['falharam']} falharam, "
          f"{s['indefinidos']} indefinidos  |  {s['ms']}ms  |  US$ {s['custo_usd']:.6f}")
    if s["indefinidos"]:
        print("INDEFINIDO não é aprovação — são casos que não deu pra julgar.")


def main() -> int:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="Arnês de avaliação do VTz OS")
    ap.add_argument("--engine", default="ollama", choices=["ollama", "openrouter"],
                    help="quem responde os casos de 'resposta' (padrão: ollama, grátis)")
    ap.add_argument("--modelo", default="", help="modelo específico")
    ap.add_argument("--alvo", default="", help="só um alvo (roteamento|fala|resposta)")
    ap.add_argument("--etiqueta", default="", help="só casos com esta etiqueta")
    ap.add_argument("--verboso", action="store_true")
    ap.add_argument("--nome", default="", help="nome do arquivo da execução")
    ap.add_argument("--sem-gravar", action="store_true")
    cfg = ap.parse_args()
    cfg.chave = os.environ.get("OPENROUTER_API_KEY", "")
    cfg.julgador = None      # juiz por LLM: opt-in, ainda não ligado por padrão

    casos = carrega()
    if cfg.alvo:
        casos = [c for c in casos if c.alvo == cfg.alvo]
    if cfg.etiqueta:
        casos = [c for c in casos if cfg.etiqueta in c.etiquetas]
    if not casos:
        print("nenhum caso casa com o filtro")
        return 1

    pagos = [c for c in casos if c.custa]
    if pagos and cfg.engine == "openrouter":
        # Avisar ANTES de gastar. Descobrir o custo no extrato é tarde demais
        # com R$ 50/mês.
        print(f"ATENÇÃO: {len(pagos)} caso(s) vão pra NUVEM e custam dinheiro.")
        print(f"         modelo: {cfg.modelo or 'padrão'}\n")
    if pagos and cfg.engine == "ollama" and not cfg.chave:
        print(f"({len(pagos)} caso(s) de resposta vão pro modelo local — sem custo)\n")

    resultado = executa(casos, cfg)
    imprime(resultado, cfg.verboso)

    if not cfg.sem_gravar:
        PASTA_EXECUCOES.mkdir(exist_ok=True)
        nome = cfg.nome or f"{resultado['quando'].replace(':', '')}-{resultado['engine']}"
        destino = PASTA_EXECUCOES / f"{nome}.json"
        destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=1),
                           encoding="utf-8")
        print(f"\ngravado: avaliacao/execucoes/{destino.name}")
        print("compare com: python avaliacao/compara.py <antes> <depois>")

    # Indefinido NÃO reprova o comando, mas falha sim. Um caso que não deu pra
    # julgar é sinal de ambiente incompleto, não de produto quebrado.
    return 1 if resultado["resumo"]["falharam"] else 0


if __name__ == "__main__":
    sys.exit(main())
