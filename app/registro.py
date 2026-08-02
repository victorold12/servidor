"""Registro genérico — declarar uma capacidade sem alterar quem a consome.

===========================================================================
O PROBLEMA QUE ELE RESOLVE

Hoje as ferramentas do agente são uma lista literal dentro de
`routers/autonomous.py`: acrescentar uma significa editar o arquivo de quem
executa o laço. Quem escreve a capacidade e quem orquestra são a mesma pessoa
por acidente de código, não por necessidade.

Um registro inverte isso. A capacidade se declara; o laço pergunta o que existe.

===========================================================================
A DECISÃO QUE FAZ ISSO VALER A PENA: CATÁLOGO ANTES DE CORPO

Cada item tem uma FICHA (nome + descrição curta, sempre carregada) e um CORPO
(as instruções inteiras, carregado só quando escolhido).

Sem essa separação, um registro é só uma lista com cerimônia. Com ela, 40
skills custam ~40 linhas de prompt em vez de 40 documentos — e o Bloco 3 mostrou
que token de prefixo reenviado é onde o dinheiro vaza.

O modelo escolhe pela ficha, e só o escolhido é carregado. É o mesmo princípio
de um índice de livro: ninguém lê o livro pra descobrir se ele serve.

===========================================================================
CARREGAMENTO PREGUIÇOSO É OBRIGATÓRIO, NÃO OTIMIZAÇÃO

`corpo` é uma função, nunca um texto. Um registro que carrega tudo na
importação leria disco (ou rede) por capacidades que ninguém vai usar naquela
conversa, e o custo apareceria no tempo de subida do servidor — longe da causa.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


class RegistroInvalido(ValueError):
    pass


@dataclass(frozen=True)
class Ficha:
    """O que sempre cabe no prompt. Curta de propósito — ver o cabeçalho."""
    nome: str
    descricao: str
    etiquetas: tuple[str, ...] = ()
    origem: str = ""

    def linha(self) -> str:
        return f"- {self.nome}: {self.descricao}"


@dataclass
class Item:
    ficha: Ficha
    _corpo: Callable[[], str]
    _cache: str | None = field(default=None, repr=False)

    def corpo(self) -> str:
        """Carrega na primeira vez que alguém pede, e só então."""
        if self._cache is None:
            self._cache = str(self._corpo() or "")
        return self._cache


class Registro:
    """Coleção nomeada de capacidades."""

    def __init__(self, tipo: str = "item"):
        self.tipo = tipo
        self._itens: dict[str, Item] = {}

    def registra(self, nome: str, descricao: str, corpo: Callable[[], str], *,
                 etiquetas=(), origem: str = "", substituir: bool = False) -> Ficha:
        nome = str(nome or "").strip()
        descricao = " ".join(str(descricao or "").split())
        if not nome:
            raise RegistroInvalido("capacidade sem nome")
        if not descricao:
            # Sem descrição, o modelo não tem como escolher — e uma capacidade
            # que ninguém consegue escolher é peso morto que ainda ocupa prompt.
            raise RegistroInvalido(f"{nome!r}: falta descrição (é por ela que se escolhe)")
        if not callable(corpo):
            raise RegistroInvalido(f"{nome!r}: corpo tem que ser função (carregamento preguiçoso)")
        if nome in self._itens and not substituir:
            # Sobrescrever calado faria duas skills com o mesmo nome virarem uma,
            # e a que sumiu não deixaria rastro.
            raise RegistroInvalido(f"{nome!r} já está registrado (use substituir=True)")

        ficha = Ficha(nome=nome, descricao=descricao,
                      etiquetas=tuple(etiquetas), origem=origem)
        self._itens[nome] = Item(ficha=ficha, _corpo=corpo)
        return ficha

    def remove(self, nome: str) -> bool:
        return self._itens.pop(nome, None) is not None

    def tem(self, nome: str) -> bool:
        return nome in self._itens

    def fichas(self, etiqueta: str = "") -> list[Ficha]:
        itens = self._itens.values()
        if etiqueta:
            itens = [i for i in itens if etiqueta in i.ficha.etiquetas]
        return sorted((i.ficha for i in itens), key=lambda f: f.nome)

    def catalogo(self, etiqueta: str = "") -> str:
        """O texto que vai pro prompt. Só fichas."""
        linhas = [f.linha() for f in self.fichas(etiqueta)]
        return "\n".join(linhas)

    def corpo(self, nome: str) -> str | None:
        """Carrega o conteúdo. `None` quando não existe — quem chama decide o
        que dizer, porque inventar corpo vazio faria o modelo agir achando que
        recebeu instrução."""
        item = self._itens.get(nome)
        return item.corpo() if item else None

    def tokens_do_catalogo(self) -> int:
        from .contexto import estima_tokens
        return estima_tokens(self.catalogo())

    def __len__(self) -> int:
        return len(self._itens)
