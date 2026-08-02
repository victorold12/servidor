"""Roteamento heurístico — escolhe o engine SEM gastar chamada.

===========================================================================
POR QUE, JÁ EXISTINDO O router_llm.py

O `router_llm.py` é bom e resolve o problema certo: um classificador escolhe o
modelo. Mas ele classifica **chamando um LLM**. Hoje isso é grátis (usa modelo
free do catálogo) — e grátis não é de graça:

  - é latência de rede ANTES de começar a pensar;
  - é uma dependência a mais pra o sistema conseguir responder;
  - é uma cota que pode acabar ou mudar de política sem aviso.

Esta heurística decide em microssegundos, offline. O `router_llm.py` não é
substituído: vira o DESEMPATE, chamado só quando os sinais locais ficam na zona
cinzenta. Heurística primeiro, classificador quando vale a pena.

===========================================================================
TRÊS ENTRADAS, E A TERCEIRA NINGUÉM TEM

O OpenJarvis roteia por complexidade. Aqui entram mais duas:

  complexidade  — quão difícil é a pergunta
  orçamento     — quanto sobrou do mês (a restrição real deste projeto)
  criticidade   — quanto custa errar

Criticidade é o eixo ausente em todo roteador que estudei. Pergunta casual e
comando que apaga arquivo têm complexidade parecida e consequências opostas.
Este projeto já classifica risco de ação no gate de 4 camadas — usar o mesmo
sinal pra escolher o modelo é reaproveitar informação que já existe.

===========================================================================
O QUE ESTA HEURÍSTICA NÃO É

Não é um classificador de qualidade. Ela não sabe se a resposta vai ser boa —
sabe dizer se a pergunta PARECE simples o bastante pra o local dar conta. Errar
pra cima (mandar pro modelo forte sem precisar) custa dinheiro; errar pra baixo
(mandar pro fraco uma pergunta difícil) custa qualidade. Na dúvida ela sobe,
porque resposta ruim é mais cara que meio centavo.
"""
import re

# Sinais de que a tarefa é difícil. Cada um vale pontos; a soma decide.
_MARCAS_CODIGO = re.compile(r"```|\bdef \b|\bclass \b|=>|;\s*$|\bimport \b|</\w+>", re.M)
# `\w*` no fim de cada raiz, e NÃO um `\b` fechando o grupo: com `\b`, a raiz
# "analis" exigia fronteira logo após o "s" — e "analise" tem um "e" ali, então
# a marca nunca casava. O mesmo valia pra toda raiz pensada pra pegar conjugação
# (compar/explic/justific...). Um teste que procurava a zona cinzenta expôs isso:
# um texto de raciocínio puro estava tirando 1 ponto.
# A ALTERNÂNCIA c/qu DO PORTUGUÊS: "explicar" tem C, "explique" tem QU. A raiz
# `explic\w*` casa com "explicação" e NÃO casa com "explique" — que é justamente
# a forma imperativa, a mais provável numa pergunta ao assistente. O mesmo em
# justificar/justifique e verificar/verifique. Custou uma investigação até os
# códigos de caractere mostrarem `e,x,p,l,i,q` onde eu esperava um `c`.
_MARCAS_RACIOCINIO = re.compile(
    r"\b(por que|porque|compar\w*|analis\w*|expli[cq]\w*|justifi[cq]\w*|"
    r"verifi[cq]\w*|demonstr\w*|arquitetur\w*|refator\w*|otimiz\w*|"
    r"debug|erros?|exceç\w*|traceback|passo a passo)\b", re.I)
_MARCAS_SIMPLES = re.compile(
    r"^\s*(oi|olá|ola|bom dia|boa tarde|boa noite|obrigad|valeu|tchau|ok|sim|não|nao)\b", re.I)

LIMIAR_LOCAL = 3      # <= isto: local dá conta
LIMIAR_NUVEM = 7      # >= isto: nuvem, sem discussão. Entre os dois: desempate


def pontua(texto: str, *, historico: int = 0, tem_ferramentas: bool = False) -> int:
    """Pontuação de dificuldade. Quanto maior, mais forte o modelo necessário."""
    t = (texto or "").strip()
    if not t:
        return 0

    p = 0

    # Tamanho é o sinal mais grosseiro e o mais confiável.
    if len(t) > 2000:
        p += 4
    elif len(t) > 600:
        p += 2
    elif len(t) > 200:
        p += 1

    if _MARCAS_CODIGO.search(t):
        p += 3
    # Conta marcas DISTINTAS, não presença. "Compare X e justifique, passo a
    # passo" é raciocínio puro em 60 caracteres — com presença simples tirava 2
    # pontos e ia pro modelo fraco. O comprimento é um proxy fraco de
    # dificuldade; acúmulo de verbos de raciocínio é forte.
    marcas = {m.lower() for m in _MARCAS_RACIOCINIO.findall(t)}
    p += min(len(marcas) * 2, 6)

    # Conversa longa carrega contexto que o modelo precisa costurar.
    if historico > 12:
        p += 2
    elif historico > 4:
        p += 1

    # Escolher ferramenta certa é onde modelo pequeno mais erra — e errar aqui
    # gasta uma rodada inteira, então o desconto do local evapora.
    #
    # 4 e não 3: com 3, um pedido curto COM ferramentas somava exatamente
    # LIMIAR_LOCAL e ia pro local — a comparação é `<=`. A intenção escrita
    # acima e a aritmética discordavam, e o teste unitário não via porque
    # afirmava só que a pontuação SOBE (`com > sem`), não que a DECISÃO muda.
    # Quem pegou foi o arnês de avaliação, no primeiro caso que exercitou o
    # resultado em vez da propriedade.
    #
    # O painel já tratava isto como regra dura (`talvezLocal` devolve null
    # quando há `tools`). Com 4 o pedido cai na zona cinzenta e sobe, que é a
    # mesma conclusão sem cravar uma exceção absoluta.
    if tem_ferramentas:
        p += 4

    # Saudação e confirmação nunca precisam de modelo forte, por mais longa que
    # a conversa esteja. Este ramo vem por último pra sobrepor o resto.
    if _MARCAS_SIMPLES.match(t) and len(t) < 80:
        return 0

    return p


def decide(texto: str, *, historico: int = 0, tem_ferramentas: bool = False,
           tem_local: bool = False, saldo_usd: float | None = None,
           critico: bool = False) -> dict:
    """Devolve `{engine, motivo, pontos, desempatar}`.

    `desempatar=True` significa "a heurística não tem convicção" — quem chamou
    pode consultar o `router_llm.py`. Não é erro: é a heurística sabendo o
    limite dela, que é melhor que fingir certeza.
    """
    p = pontua(texto, historico=historico, tem_ferramentas=tem_ferramentas)

    # CRITICIDADE vence tudo. Ação que apaga arquivo ou manda e-mail merece o
    # modelo bom mesmo com orçamento apertado: economizar meio centavo e errar
    # o comando sai muito mais caro que a economia.
    if critico:
        return {"engine": "openrouter", "motivo": "tarefa crítica: erro sai caro",
                "pontos": p, "desempatar": False}

    if not tem_local:
        return {"engine": "openrouter", "motivo": "não há modelo local nesta máquina",
                "pontos": p, "desempatar": False}

    # ORÇAMENTO. Sem saldo, local é a única opção que não custa — e responder
    # com modelo fraco é melhor que não responder. Isto é o governador de
    # orçamento: a restrição vira comportamento, não relatório.
    if saldo_usd is not None and saldo_usd <= 0:
        return {"engine": "ollama", "motivo": "orçamento do mês esgotado",
                "pontos": p, "desempatar": False}

    if p <= LIMIAR_LOCAL:
        return {"engine": "ollama", "motivo": f"pergunta simples ({p} ponto(s))",
                "pontos": p, "desempatar": False}
    if p >= LIMIAR_NUVEM:
        return {"engine": "openrouter", "motivo": f"pergunta difícil ({p} pontos)",
                "pontos": p, "desempatar": False}

    # Zona cinzenta: sobe pra nuvem por padrão (errar pra baixo custa qualidade,
    # que é mais caro que meio centavo), mas avisa que vale desempatar.
    return {"engine": "openrouter", "motivo": f"na dúvida ({p} pontos)",
            "pontos": p, "desempatar": True}
