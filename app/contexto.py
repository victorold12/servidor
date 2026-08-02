"""Compressão de contexto — pagar menos pela mesma conversa.

===========================================================================
ONDE O DINHEIRO VAZA

O agente autônomo (`routers/autonomous.py`) faz `messages.append` dentro de um
laço e **reenvia a lista inteira** a cada volta. Com 12 passos, o primeiro
prompt é cobrado 12 vezes; e as observações de ferramenta que entram no meio são
conteúdo de arquivo e resultado de busca — as maiores mensagens da conversa.

O custo cresce com o quadrado dos passos. Numa tarefa que lê três arquivos
grandes, o gasto está quase todo em reenviar o que o modelo já viu.

Uma conversa de chat também cresce, mas é limitada pela paciência de quem
digita. O laço do agente é limitado só por `max_steps`.

===========================================================================
A ARMADILHA QUE DEFINE O DESENHO

No formato da OpenAI, uma mensagem `role="tool"` só é válida logo depois da
mensagem do assistente que pediu aquela ferramenta, casando por
`tool_call_id`. Cortar a do assistente e manter a da ferramenta produz um
histórico que o provedor RECUSA — erro 400 no meio de uma tarefa longa, que é o
pior momento possível.

Por isso nada aqui corta mensagem solta. A unidade de descarte é o TURNO:
a mensagem do assistente e todas as respostas de ferramenta que ela gerou saem
juntas ou ficam juntas.

===========================================================================
A ORDEM DOS CORTES, E POR QUÊ

1. **Encurtar observação de ferramenta antiga.** É o corte de melhor relação
   economia/dano: um `read_file` de 400 linhas foi útil no passo 3 e no passo 9
   o modelo já extraiu o que precisava. Guarda-se o começo e o fim, que é onde
   mora a estrutura.
2. **Encurtar observação recente também**, se o passo 1 não bastou — menos o
   último turno, que é o que está sendo resolvido agora. Todo o encurtamento
   vem antes de qualquer descarte porque encurtar dana menos: o modelo continua
   sabendo que a ferramenta rodou e o que ela devolveu em linhas gerais.
3. **Descartar turnos antigos inteiros.** Só quando encurtar tudo não bastou.
4. **Resumir o que foi descartado**, se houver resumidor. Sem ele, o corte é
   anunciado no lugar — melhor um buraco declarado que um buraco silencioso.

O que NUNCA é tocado: a mensagem de sistema (é o contrato, e sem ela o modelo
muda de comportamento) e o último turno.

===========================================================================
QUANDO NEM ASSIM CABE

A primeira versão disto devolvia acima do teto dizendo que tinha comprimido:
com a janela recente maior que o orçamento, não havia mais nada que ela se
permitisse cortar. Um teto que não é respeitado nem avisado é pior que nenhum,
porque quem chamou passa a confiar num número errado.

Hoje o relatório traz `coube`. Falso significa "fiz tudo que dava e ainda não
entra" — e aí a decisão é de quem chamou: modelo de contexto maior, tarefa
menor, ou seguir e aceitar o risco de o provedor recusar.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

# Aproximação: ~4 caracteres por token. É uma estimativa, não uma medida — o
# tokenizador real varia por modelo, e português gasta um pouco mais que inglês
# por causa dos acentos. Serve porque a decisão aqui é grosseira ("cabe ou não
# cabe"), e um erro de 20% muda o momento do corte, não a correção dele.
#
# Não vale trazer `tiktoken` pra isso: é dependência pesada, específica da
# OpenAI, e erraria igual nos modelos dos outros provedores.
CHARS_POR_TOKEN = 4


def estima_tokens(conteudo) -> int:
    """Estimativa de tokens de uma mensagem ou de um texto."""
    if conteudo is None:
        return 0
    if isinstance(conteudo, str):
        return len(conteudo) // CHARS_POR_TOKEN + 1
    if isinstance(conteudo, dict):
        # Mensagem inteira: conta o texto e a papelada (tool_calls viram JSON no
        # fio e são cobrados como qualquer outro token).
        total = estima_tokens(conteudo.get("content"))
        if conteudo.get("tool_calls"):
            total += estima_tokens(json.dumps(conteudo["tool_calls"], ensure_ascii=False))
        return total + 4          # sobrecarga de papel/delimitadores por mensagem
    if isinstance(conteudo, list):
        return sum(estima_tokens(x) for x in conteudo)
    return estima_tokens(str(conteudo))


@dataclass
class Turno:
    """Assistente + as respostas de ferramenta que ele gerou, ou uma mensagem
    solta. A unidade indivisível — ver o cabeçalho."""
    mensagens: list[dict] = field(default_factory=list)

    @property
    def tokens(self) -> int:
        return estima_tokens(self.mensagens)


def agrupa(mensagens: list[dict]) -> list[Turno]:
    """Junta cada assistente com suas respostas de ferramenta."""
    turnos: list[Turno] = []
    for m in mensagens:
        papel = m.get("role")
        # `tool` sempre pertence ao turno anterior. Se aparecer sem dono (não
        # deveria), vira turno próprio em vez de sumir — perder mensagem
        # calada seria trocar um defeito por outro mais difícil de ver.
        if papel == "tool" and turnos:
            turnos[-1].mensagens.append(m)
        else:
            turnos.append(Turno([m]))
    return turnos


def _encurta_texto(texto: str, teto_chars: int) -> str:
    """Guarda começo e fim. O meio de um despejo de arquivo é o menos informativo:
    o começo tem a estrutura, o fim tem a conclusão."""
    if len(texto) <= teto_chars:
        return texto
    metade = max(200, (teto_chars - 80) // 2)
    cortados = len(texto) - metade * 2
    return (texto[:metade]
            + f"\n\n[… {cortados} caracteres omitidos pela compressão de contexto …]\n\n"
            + texto[-metade:])


@dataclass
class Relatorio:
    """O que foi feito. Comprimir em silêncio esconderia a causa de uma resposta
    pior — o modelo passa a não ver algo que via, e ninguém liga uma coisa à
    outra."""
    comprimiu: bool = False
    tokens_antes: int = 0
    tokens_depois: int = 0
    ferramentas_encurtadas: int = 0
    turnos_descartados: int = 0
    resumiu: bool = False
    # Falso = fiz tudo que dava e ainda estoura. Ver o cabeçalho: um teto que
    # não é respeitado nem avisado é pior que teto nenhum.
    coube: bool = True

    @property
    def economia(self) -> int:
        return max(0, self.tokens_antes - self.tokens_depois)

    def __str__(self) -> str:
        if not self.comprimiu:
            return f"sem compressão ({self.tokens_antes} tokens estimados)"
        partes = []
        if self.ferramentas_encurtadas:
            partes.append(f"{self.ferramentas_encurtadas} observação(ões) encurtada(s)")
        if self.turnos_descartados:
            partes.append(f"{self.turnos_descartados} turno(s) descartado(s)"
                          + (" e resumidos" if self.resumiu else ""))
        aviso = "" if self.coube else "  ATENÇÃO: ainda acima do teto"
        return (f"{self.tokens_antes} -> {self.tokens_depois} tokens estimados "
                f"({', '.join(partes) or 'nada'}){aviso}")


def comprime(mensagens: list[dict], *, teto_tokens: int,
             manter_recentes: int = 6, teto_ferramenta_chars: int = 2000,
             resumidor=None) -> tuple[list[dict], Relatorio]:
    """Devolve `(mensagens, relatorio)`.

    `resumidor(mensagens) -> str` é opcional e CUSTA (é uma chamada de modelo).
    Sem ele, os turnos descartados viram um aviso no lugar — um buraco declarado
    é melhor que um buraco silencioso, porque o modelo pode dizer "não tenho
    essa parte" em vez de inventar.
    """
    rel = Relatorio(tokens_antes=estima_tokens(mensagens))
    rel.tokens_depois = rel.tokens_antes
    if rel.tokens_antes <= teto_tokens or not mensagens:
        return mensagens, rel

    turnos = agrupa(mensagens)

    # A mensagem de sistema é o contrato: sem ela o modelo muda de comportamento,
    # e economizar aqui trocaria custo por imprevisibilidade.
    inicio = 1 if turnos and turnos[0].mensagens[0].get("role") == "system" else 0
    fixos_ini = turnos[:inicio]

    # Os recentes são o que está sendo resolvido agora.
    n_recentes = min(manter_recentes, max(0, len(turnos) - inicio))
    recentes = turnos[len(turnos) - n_recentes:] if n_recentes else []
    miolo = turnos[inicio:len(turnos) - n_recentes] if n_recentes else turnos[inicio:]

    def monta():
        return [m for t in fixos_ini + miolo + recentes for m in t.mensagens]

    def encurta_em(turnos_alvo) -> None:
        for t in turnos_alvo:
            for m in t.mensagens:
                if m.get("role") == "tool" and isinstance(m.get("content"), str):
                    original = m["content"]
                    novo = _encurta_texto(original, teto_ferramenta_chars)
                    if novo != original:
                        m["content"] = novo
                        rel.ferramentas_encurtadas += 1

    # ---- Corte 1: encurtar observação de ferramenta no miolo ----
    encurta_em(miolo)
    rel.tokens_depois = estima_tokens(monta())
    rel.comprimiu = rel.ferramentas_encurtadas > 0
    if rel.tokens_depois <= teto_tokens:
        rel.coube = True
        return monta(), rel

    # ---- Corte 2: encurtar também o recente, menos o último turno ----
    #
    # Sem isto, uma janela recente maior que o teto era intocável e a função
    # devolvia acima do orçamento dizendo que tinha comprimido. Encurtar aqui
    # ainda dana menos que descartar turno: o modelo continua sabendo que a
    # ferramenta rodou e o que ela devolveu em linhas gerais.
    #
    # O ÚLTIMO turno fica inteiro sempre: é o que está sendo resolvido agora, e
    # cortá-lo trocaria economia por burrice imediata.
    if recentes:
        encurta_em(recentes[:-1])
        rel.comprimiu = rel.comprimiu or rel.ferramentas_encurtadas > 0
        rel.tokens_depois = estima_tokens(monta())
        if rel.tokens_depois <= teto_tokens:
            rel.coube = True
            return monta(), rel

    # ---- Corte 3: descartar turnos antigos do miolo, do mais velho pro mais novo ----
    descartados: list[dict] = []
    while miolo and estima_tokens(monta()) > teto_tokens:
        alvo = miolo.pop(0)
        descartados.extend(alvo.mensagens)
        rel.turnos_descartados += 1

    # ---- Corte 4: encolher a própria janela recente, se ainda não coube ----
    #
    # `manter_recentes` é uma PREFERÊNCIA; o teto é o CONTRATO. Quando os dois
    # brigam, quem cede é a preferência — estourar o contexto derruba a chamada
    # inteira, enquanto ver menos histórico só piora a resposta.
    #
    # Nunca desce abaixo de um turno: o último é o que está sendo resolvido
    # agora, e sem ele não sobra pergunta pra responder. Se nem ele couber
    # sozinho, `coube` sai falso e a decisão volta pra quem chamou.
    while len(recentes) > 1 and estima_tokens(monta()) > teto_tokens:
        alvo = recentes.pop(0)
        descartados.extend(alvo.mensagens)
        rel.turnos_descartados += 1

    if descartados:
        rel.comprimiu = True
        nota = None
        if resumidor is not None:
            try:
                texto = resumidor(descartados)
                if texto and str(texto).strip():
                    nota = ("[resumo do trecho anterior desta conversa, comprimido "
                            f"para caber no contexto]\n{texto}")
                    rel.resumiu = True
            except Exception:
                # Resumidor que falha não pode derrubar a conversa: o aviso
                # abaixo cobre o caso, e uma tarefa longa morrer por causa da
                # OTIMIZAÇÃO seria o pior desfecho possível.
                nota = None
        if nota is None:
            nota = (f"[{rel.turnos_descartados} turno(s) mais antigo(s) desta conversa "
                    "foram removidos para caber no contexto. Se precisar de algo "
                    "desse trecho, diga que não tem a informação em vez de supor.]")
        miolo.insert(0, Turno([{"role": "system", "content": nota}]))

    montado = monta()
    rel.tokens_depois = estima_tokens(montado)
    rel.coube = rel.tokens_depois <= teto_tokens
    return montado, rel
