"""Compara duas execuções. É aqui que o arnês vira detector de regressão.

===========================================================================
POR QUE UMA EXECUÇÃO SOZINHA NÃO SERVE

"18 de 20 passaram" não diz nada sem o número de ontem. Pode ser o melhor
resultado da história ou o pior — o placar absoluto de um arnês é quase sempre
ruído, porque os casos difíceis foram escolhidos justamente por serem difíceis.

O que informa é a MUDANÇA, e uma mudança em particular: o caso que passava e
parou de passar. Esse é o único evento que exige ação imediata, e é o que este
arquivo procura primeiro.

===========================================================================
POR QUE REGRESSÃO E MELHORIA NÃO SE COMPENSAM

A tentação é somar: "duas quebraram, três consertaram, saldo positivo". Não.
Uma regressão é uma promessa desfeita — alguma coisa que funcionava na mão do
Victor deixou de funcionar. Três melhorias não devolvem isso. Por isso o código
de saída olha só as regressões.

===========================================================================
O QUE "SUMIU" SIGNIFICA

Caso que existia antes e não existe agora. Quase sempre é edição de arquivo de
casos, mas merece linha própria: apagar o caso que estava vermelho é a forma
mais fácil (e mais tentadora) de deixar o arnês verde.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

AQUI = pathlib.Path(__file__).resolve().parent
PASTA_EXECUCOES = AQUI / "execucoes"

_ROTULO = {True: "passou", False: "FALHOU", None: "indefinido"}

# Alvos cujo resultado depende do modelo, não só do código. `roteamento` e
# `fala` são funções puras: mesma entrada, mesma saída, sempre. `resposta` não.
ALVOS_ESTOCASTICOS = {"resposta"}


def _carrega(ref: str) -> dict:
    """Aceita caminho, nome do arquivo, ou 'ultima'/'penultima'."""
    if ref in ("ultima", "penultima"):
        arqs = sorted(PASTA_EXECUCOES.glob("*.json"), key=lambda p: p.stat().st_mtime)
        if not arqs:
            raise SystemExit("nenhuma execução gravada ainda")
        idx = -1 if ref == "ultima" else -2
        if len(arqs) < abs(idx):
            raise SystemExit(f"não há execução suficiente pra {ref!r} ({len(arqs)} gravada(s))")
        return json.loads(arqs[idx].read_text(encoding="utf-8"))

    p = pathlib.Path(ref)
    for cand in (p, PASTA_EXECUCOES / ref, PASTA_EXECUCOES / f"{ref}.json"):
        if cand.is_file():
            return json.loads(cand.read_text(encoding="utf-8"))
    raise SystemExit(f"não achei a execução {ref!r}")


def compara(antes: dict, depois: dict) -> dict:
    a = {r["id"]: r for r in antes["resultados"]}
    d = {r["id"]: r for r in depois["resultados"]}

    regressoes, melhorias, mudou_indefinido = [], [], []
    for cid in sorted(set(a) & set(d)):
        va, vd = a[cid]["passou"], d[cid]["passou"]
        if va == vd:
            continue
        item = {"id": cid, "de": va, "para": vd,
                "detalhe": _primeiro_motivo(d[cid]), "alvo": d[cid].get("alvo", "")}
        if va is True and vd is not True:
            regressoes.append(item)          # passava e parou: o evento que importa
        elif va is not True and vd is True:
            melhorias.append(item)
        else:
            # falhou <-> indefinido. Não é conserto nem quebra, mas esconder
            # faria "falhou" virar "indefinido" sem ninguém notar — e
            # indefinido é confortável demais pra ser invisível.
            mudou_indefinido.append(item)

    return {
        "regressoes": regressoes,
        "melhorias": melhorias,
        "mudou_indefinido": mudou_indefinido,
        "novos": sorted(set(d) - set(a)),
        "sumiram": sorted(set(a) - set(d)),
        "custo": (antes["resumo"].get("custo_usd", 0), depois["resumo"].get("custo_usd", 0)),
        "ms": (antes["resumo"].get("ms", 0), depois["resumo"].get("ms", 0)),
    }


def _primeiro_motivo(resultado: dict) -> str:
    if resultado.get("erro"):
        return resultado["erro"]
    for n in resultado.get("notas", []):
        if n.get("passou") is not True:
            return f"{n.get('criterio')}: {n.get('detalhe')}"
    return ""


def imprime(antes: dict, depois: dict, dif: dict) -> None:
    def cab(e):
        s = e["resumo"]
        return (f"{e.get('git', '?')} {e.get('engine', '?')}"
                f"{'/' + e['modelo'] if e.get('modelo') else ''}  "
                f"{s['passaram']}/{s['total']}  {e.get('quando', '')}")

    print(f"antes : {cab(antes)}")
    print(f"depois: {cab(depois)}\n")

    if dif["regressoes"]:
        print(f"REGRESSÕES ({len(dif['regressoes'])}) — passavam e pararam:")
        for r in dif["regressoes"]:
            print(f"  {r['id']:<28} {_ROTULO[r['de']]} -> {_ROTULO[r['para']]}")
            if r["detalhe"]:
                print(f"      {r['detalhe']}")
        print()
        if any(r["alvo"] in ALVOS_ESTOCASTICOS for r in dif["regressoes"]):
            # Honestidade sobre o próprio instrumento. A primeira comparação
            # feita com este arquivo acusou uma regressão que não existia: era o
            # modelo respondendo diferente na mesma versão do código. Hoje o
            # arnês roda com `temperature: 0` e isso ficou raro — mas raro não é
            # nunca, e apresentar as duas classes com a mesma cara faria a
            # pessoa desconfiar de código são.
            print("  ^ alvo 'resposta' depende do modelo e pode variar mesmo sem")
            print("    mudança de código. Rode de novo antes de investigar:")
            print("      python avaliacao/executa.py --alvo resposta\n")

    if dif["melhorias"]:
        print(f"melhorias ({len(dif['melhorias'])}):")
        for r in dif["melhorias"]:
            print(f"  {r['id']:<28} {_ROTULO[r['de']]} -> {_ROTULO[r['para']]}")
        print()

    if dif["mudou_indefinido"]:
        print(f"mudaram de/para indefinido ({len(dif['mudou_indefinido'])}):")
        for r in dif["mudou_indefinido"]:
            print(f"  {r['id']:<28} {_ROTULO[r['de']]} -> {_ROTULO[r['para']]}")
            if r["detalhe"]:
                print(f"      {r['detalhe']}")
        print()

    if dif["sumiram"]:
        print(f"SUMIRAM ({len(dif['sumiram'])}) — apagar o caso vermelho também deixa verde:")
        for cid in dif["sumiram"]:
            print(f"  {cid}")
        print()

    if dif["novos"]:
        print(f"novos ({len(dif['novos'])}): {', '.join(dif['novos'])}\n")

    ca, cd = dif["custo"]
    ma, md = dif["ms"]
    print(f"custo: US$ {ca:.6f} -> US$ {cd:.6f}      tempo: {ma}ms -> {md}ms")

    if not any([dif["regressoes"], dif["melhorias"], dif["mudou_indefinido"],
                dif["novos"], dif["sumiram"]]):
        print("\nnenhuma mudança de veredito.")


def main() -> int:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(
        description="Compara duas execuções do arnês (aceita 'ultima' e 'penultima')")
    ap.add_argument("antes")
    ap.add_argument("depois", nargs="?", default="ultima")
    cfg = ap.parse_args()

    antes, depois = _carrega(cfg.antes), _carrega(cfg.depois)
    dif = compara(antes, depois)
    imprime(antes, depois, dif)

    # Só regressão reprova. Ver o cabeçalho: melhoria não compensa quebra, e
    # indefinido novo é sinal de ambiente, não de produto.
    return 1 if dif["regressoes"] else 0


if __name__ == "__main__":
    sys.exit(main())
