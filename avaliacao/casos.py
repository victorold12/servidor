"""Os casos: o que o arnês pergunta e o que espera.

Formato JSONL — uma linha por caso. Escolhido em vez de um JSON grande porque o
diff fica legível: acrescentar caso é uma linha nova, e a revisão mostra
exatamente o que mudou. Num array JSON, acrescentar no fim mexe na vírgula da
linha anterior e polui o diff.

===========================================================================
O QUE É RECUSADO NO CARREGAMENTO, E POR QUÊ

**Caso sem critério.** Ele passaria sempre — `veredito([])` é indefinido, mas o
perigo real é psicológico: vinte casos sem critério dão um placar de vinte
"não falhou" que se lê como vinte aprovações. Um arnês que infla o próprio
placar é pior que nenhum.

**Id repetido.** Duas linhas com o mesmo id fazem a comparação entre execuções
casar o caso errado, e o relatório de regressão passa a mentir sem dar sinal.

**Alvo desconhecido.** Um typo em `alvo` faria o caso ser pulado em silêncio.
Pular em silêncio é como se perde cobertura sem ninguém perceber — foi assim
que o `41-matematica.js` ficou meses fora do bundle.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field

AQUI = pathlib.Path(__file__).resolve().parent
PASTA_CASOS = AQUI / "casos"

# Cada alvo é um jeito diferente de exercitar o sistema. Ver executa.py.
ALVOS = {
    "roteamento",   # decide() escolhe o engine certo? Não chama modelo: grátis.
    "resposta",     # o modelo responde bem? Chama modelo.
    "fala",         # o texto que vai pra voz está limpo? Não chama modelo.
}


@dataclass
class Caso:
    id: str
    alvo: str
    entrada: str
    criterios: list[dict]
    contexto: dict = field(default_factory=dict)
    etiquetas: list[str] = field(default_factory=list)

    @property
    def custa(self) -> bool:
        """Só `resposta` gasta. Saber disso ANTES de rodar é o que permite
        avisar o custo antes de cobrá-lo."""
        return self.alvo == "resposta"


class CasoInvalido(ValueError):
    pass


def _valida(bruto: dict, origem: str, linha: int) -> Caso:
    onde = f"{origem}:{linha}"
    for campo in ("id", "alvo", "entrada"):
        if not str(bruto.get(campo) or "").strip():
            raise CasoInvalido(f"{onde}: falta {campo!r}")

    alvo = bruto["alvo"]
    if alvo not in ALVOS:
        raise CasoInvalido(
            f"{onde}: alvo {alvo!r} desconhecido (conhecidos: {', '.join(sorted(ALVOS))})")

    criterios = bruto.get("criterios") or []
    if not isinstance(criterios, list) or not criterios:
        raise CasoInvalido(f"{onde}: caso sem critério passaria sempre — ver o cabeçalho")
    for c in criterios:
        if not isinstance(c, dict) or "tipo" not in c:
            raise CasoInvalido(f"{onde}: critério sem 'tipo': {c!r}")

    return Caso(
        id=bruto["id"], alvo=alvo, entrada=bruto["entrada"],
        criterios=criterios,
        contexto=bruto.get("contexto") or {},
        etiquetas=bruto.get("etiquetas") or [],
    )


def carrega(pasta: pathlib.Path | None = None) -> list[Caso]:
    pasta = pasta or PASTA_CASOS
    casos: list[Caso] = []
    vistos: dict[str, str] = {}

    for arq in sorted(pasta.glob("*.jsonl")):
        for n, linha in enumerate(arq.read_text(encoding="utf-8").splitlines(), 1):
            linha = linha.strip()
            if not linha or linha.startswith("//"):
                continue
            try:
                bruto = json.loads(linha)
            except json.JSONDecodeError as e:
                raise CasoInvalido(f"{arq.name}:{n}: JSON inválido — {e}") from e
            caso = _valida(bruto, arq.name, n)
            if caso.id in vistos:
                raise CasoInvalido(
                    f"{arq.name}:{n}: id {caso.id!r} repetido (já em {vistos[caso.id]})")
            vistos[caso.id] = f"{arq.name}:{n}"
            casos.append(caso)

    return casos
