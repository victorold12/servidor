"""Procedência — lembrar de ONDE cada pedaço de texto veio.

===========================================================================
A IDEIA, EM UMA FRASE

Texto que veio de fora não pode virar ordem lá dentro.

Os dois módulos vizinhos olham o CONTEÚDO: `injecao` procura padrão de ataque,
`credenciais` procura segredo. Os dois erram por construção — nenhum reconhece o
que nunca viu. Este olha o CAMINHO, e o caminho não depende de reconhecer nada.

Uma página web maliciosa pode escrever a instrução de um jeito que nenhum regex
pega. O que ela não consegue mudar é o fato de ter vindo de `fetch_url`.

===========================================================================
COMO SE USA

    t = Texto.externo(html, origem="fetch_url:exemplo.com")
    ...
    guarda_sumidouro(t, "comando")     # levanta: externo não vira comando

`Texto` se comporta como string onde só se lê. O que ele não deixa é passar
calado por um ponto perigoso.

===========================================================================
OS SUMIDOUROS, E POR QUE SÓ ESTES

Um sumidouro é um ponto onde texto vira consequência:

  comando   — vai virar execução no PC
  arquivo   — vai virar caminho de escrita
  rede      — vai virar destino de envio
  segredo   — vai ser comparado com credencial

Fora daí, texto externo circula à vontade: resumir uma página, traduzir um
e-mail, citar uma busca. Marcar tudo como perigoso treinaria todo mundo a
ignorar o aviso, que é como um alarme morre.

===========================================================================
O QUE ISTO NÃO É

Não é rastreamento de fluxo de dados de verdade — Python não permite isso sem
instrumentar o interpretador. Se alguém fizer `str(t)` ou `t.texto`, a marca
some, e é assim mesmo: a marca serve pra quem está tentando acertar, não pra
conter quem está tentando burlar. Contra o segundo, o que vale é o gate de 4
camadas, que decide no PC e não confia em nada que veio da nuvem.
"""
from __future__ import annotations

from dataclasses import dataclass, field

CONFIAVEL = "confiavel"      # o Victor digitou, ou o próprio sistema gerou
EXTERNO = "externo"          # web, e-mail, skill de terceiro, resultado de busca

SUMIDOUROS = {
    "comando": "virar execução no PC",
    "arquivo": "virar caminho de escrita",
    "rede": "virar destino de envio",
    "segredo": "ser comparado com credencial",
}


class ProcedenciaNegada(PermissionError):
    """Texto externo tentou entrar num ponto onde vira consequência."""


@dataclass(frozen=True)
class Texto:
    texto: str
    procedencia: str = CONFIAVEL
    origem: str = ""
    # Quando um texto nasce da junção de vários, a procedência mais fraca manda.
    # Guardar as origens permite dizer DE ONDE veio a contaminação, que é a
    # primeira pergunta de quem investiga.
    origens: tuple[str, ...] = field(default_factory=tuple)

    @staticmethod
    def confiavel(texto: str, origem: str = "usuario") -> "Texto":
        return Texto(str(texto or ""), CONFIAVEL, origem, (origem,) if origem else ())

    @staticmethod
    def externo(texto: str, origem: str) -> "Texto":
        return Texto(str(texto or ""), EXTERNO, origem, (origem,) if origem else ())

    @property
    def suspeito(self) -> bool:
        return self.procedencia == EXTERNO

    def __str__(self) -> str:
        return self.texto

    def __len__(self) -> int:
        return len(self.texto)

    def __contains__(self, outro) -> bool:
        return str(outro) in self.texto

    def concatena(self, outro) -> "Texto":
        """Junta preservando a pior procedência.

        Confiável + externo = externo, sempre. É a única regra que faz sentido:
        um prompt montado com um pedaço de página web contém aquele pedaço, e
        o pedaço não fica mais seguro por estar acompanhado.
        """
        if isinstance(outro, Texto):
            proc = EXTERNO if EXTERNO in (self.procedencia, outro.procedencia) else CONFIAVEL
            return Texto(self.texto + outro.texto, proc,
                         self.origem or outro.origem,
                         tuple(dict.fromkeys(self.origens + outro.origens)))
        return Texto(self.texto + str(outro), self.procedencia, self.origem, self.origens)

    __add__ = concatena


def guarda_sumidouro(valor, sumidouro: str, *, permitir_externo: bool = False) -> str:
    """Deixa passar, ou levanta. Devolve a string crua quando aprova.

    `permitir_externo=True` existe pro caso legítimo em que o usuário viu o
    conteúdo e aprovou — mas quem chama tem que escrever isso, e escrever é o
    ponto: a permissão fica visível no código e no diff, em vez de acontecer por
    omissão.
    """
    if sumidouro not in SUMIDOUROS:
        raise ValueError(f"sumidouro desconhecido: {sumidouro!r}")
    if not isinstance(valor, Texto):
        # String crua não tem procedência conhecida. Tratar como confiável seria
        # cômodo e errado; é justamente o caminho por onde a marca se perde.
        return str(valor)
    if valor.suspeito and not permitir_externo:
        raise ProcedenciaNegada(
            f"texto de {valor.origem or 'origem externa'} não pode {SUMIDOUROS[sumidouro]}. "
            "Se a intenção é essa, quem chama precisa dizer permitir_externo=True.")
    return valor.texto


def relatorio(valor) -> dict:
    if not isinstance(valor, Texto):
        return {"procedencia": "desconhecida", "origens": []}
    return {"procedencia": valor.procedencia, "origens": list(valor.origens)}
