"""Árvore de acessibilidade — a página como um leitor de tela a vê.

===========================================================================
POR QUE NÃO É "MANDAR O HTML PRO MODELO"

O HTML de uma página comum tem 300 KB e é quase todo `<div class="css-1x2y3z">`.
Mandar isso custa dezenas de milhares de tokens pra transmitir uma estrutura que
cabe em vinte linhas — e o modelo ainda tem que adivinhar o que é clicável.

A árvore de acessibilidade é a mesma página descrita por PAPEL: isto é um botão,
isto é um campo de busca, isto é um link para tal lugar. É o que um leitor de
tela usa, e é a representação certa para um agente pelo mesmo motivo — os dois
precisam operar a página sem enxergá-la.

===========================================================================
POR QUE SEM NAVEGADOR

Um navegador de verdade daria a árvore exata, com estado calculado. Também
custaria 400 MB de Chromium, um processo por página e um ambiente que o Render
grátis não comporta. Este módulo extrai do HTML estático, o que perde o que
depende de JavaScript — e é honesto quanto a isso: `avisos` diz quando a página
parece depender de script pra ter conteúdo.

Meio caminho declarado é melhor que caminho inteiro prometido e não entregue.

===========================================================================
SEGURANÇA

O texto extraído VEM DE FORA. Ele sai daqui marcado como externo
(`taint.Texto.externo`) e envelopado (`injecao.envelopa`), porque conteúdo de
página é o vetor de injeção mais comum que existe: qualquer um publica uma.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

# Elementos que carregam PAPEL. O resto do HTML é apresentação, e apresentação
# é exatamente o que não interessa a quem opera a página sem ver.
_PAPEIS = {
    "a": "link", "button": "botão", "input": "campo", "textarea": "campo",
    "select": "seleção", "form": "formulário", "nav": "navegação",
    "h1": "título", "h2": "título", "h3": "título", "h4": "título",
    "main": "principal", "table": "tabela", "img": "imagem",
    "label": "rótulo", "option": "opção", "summary": "expansor",
}
# `head` NÃO entra aqui, e isso custou um teste: com ele na lista, o contador de
# ignorados subia ao abrir o `<head>` e o `<title>` era descartado antes de ser
# lido — a página vinha sem título. Os filhos do head que importam ignorar
# (script, style, meta, link) já estão listados um a um, então `head` era
# redundante e ainda por cima destrutivo.
_IGNORAR = {"script", "style", "noscript", "svg", "path", "meta", "link"}


@dataclass
class No:
    papel: str
    nome: str = ""
    valor: str = ""
    filhos: list["No"] = field(default_factory=list)

    def linha(self, nivel: int = 0) -> str:
        partes = [f'{"  " * nivel}{self.papel}']
        if self.nome:
            partes.append(f'"{self.nome}"')
        if self.valor:
            partes.append(f"→ {self.valor}")
        return " ".join(partes)

    def texto(self, nivel: int = 0, teto: int = 200) -> str:
        linhas = [self.linha(nivel)]
        for f in self.filhos:
            if len(linhas) >= teto:
                linhas.append(f'{"  " * (nivel + 1)}… (cortado)')
                break
            linhas.append(f.texto(nivel + 1, teto - len(linhas)))
        return "\n".join(linhas)


class _Extrator(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.raiz = No("página")
        self.pilha = [self.raiz]
        self.ignorando = 0
        self.titulo = ""
        self._em_titulo = False
        self.scripts = 0
        self.texto_bruto = 0

    def handle_starttag(self, tag, attrs):
        if tag in _IGNORAR:
            self.ignorando += 1
            if tag in ("script", "noscript"):
                self.scripts += 1
            return
        if self.ignorando:
            return
        a = dict(attrs)
        if tag == "title":
            self._em_titulo = True
            return

        papel = a.get("role") or _PAPEIS.get(tag)
        if not papel:
            return

        # `aria-label` primeiro: é o nome que o autor escreveu PARA quem não vê,
        # então é o mais confiável quando existe.
        nome = (a.get("aria-label") or a.get("alt") or a.get("placeholder")
                or a.get("title") or a.get("name") or "").strip()
        valor = ""
        if tag == "a":
            valor = (a.get("href") or "").strip()[:120]
        elif tag == "input":
            valor = (a.get("type") or "text").strip()
            if a.get("value"):
                nome = nome or a["value"].strip()

        no = No(papel=papel, nome=nome[:120], valor=valor)
        self.pilha[-1].filhos.append(no)
        self.pilha.append(no)

    def handle_endtag(self, tag):
        if tag in _IGNORAR:
            self.ignorando = max(0, self.ignorando - 1)
            return
        if tag == "title":
            self._em_titulo = False
            return
        if self.ignorando:
            return
        if (tag in _PAPEIS or tag == "div") and len(self.pilha) > 1:
            # Só desempilha se o topo foi empilhado por esta tag. HTML real vem
            # com tag não fechada o tempo todo, e desempilhar cegamente
            # embaralharia a árvore inteira a partir do primeiro erro.
            if self.pilha[-1].papel == _PAPEIS.get(tag):
                self.pilha.pop()

    def handle_data(self, dados):
        if self.ignorando:
            return
        texto = " ".join(dados.split())
        if not texto:
            return
        self.texto_bruto += len(texto)
        if self._em_titulo:
            self.titulo = texto[:200]
            return
        topo = self.pilha[-1]
        if not topo.nome and topo is not self.raiz:
            topo.nome = texto[:120]
        elif topo is self.raiz and len(texto) > 40:
            # Parágrafo solto: vira nó de texto pra não sumir da árvore.
            topo.filhos.append(No("texto", texto[:200]))


@dataclass
class Pagina:
    titulo: str
    arvore: No
    avisos: list[str] = field(default_factory=list)

    def resumo(self, teto: int = 200) -> str:
        cab = f"título: {self.titulo}" if self.titulo else "título: (sem)"
        av = ("\navisos: " + "; ".join(self.avisos)) if self.avisos else ""
        return f"{cab}{av}\n{self.arvore.texto(teto=teto)}"


def extrai(html: str) -> Pagina:
    p = _Extrator()
    try:
        p.feed(html or "")
    except Exception:
        # HTML quebrado é o caso comum, não a exceção. O que foi montado até o
        # erro ainda vale mais que nada.
        pass

    avisos = []
    if p.texto_bruto < 200 and p.scripts > 0:
        # Diz o que NÃO conseguiu, em vez de entregar uma árvore vazia como se
        # a página fosse vazia — que é o mesmo erro do "existe vs funciona".
        avisos.append("quase sem texto e com scripts: a página provavelmente "
                      "monta o conteúdo com JavaScript, que este extrator não roda")
    if not p.raiz.filhos:
        avisos.append("nenhum elemento com papel reconhecido")
    return Pagina(titulo=p.titulo, arvore=p.raiz, avisos=avisos)


def para_o_modelo(html: str, origem: str):
    """Extrai e devolve pronto pro prompt: marcado como externo e envelopado.

    As duas coisas juntas de propósito. Conteúdo de página é o vetor de injeção
    mais comum que existe — qualquer um publica uma —, e entregá-lo cru seria
    convidar o modelo a obedecer ao site.
    """
    from .injecao import envelopa
    from .taint import Texto

    pagina = extrai(html)
    return Texto.externo(envelopa(pagina.resumo(), origem), origem=origem), pagina
