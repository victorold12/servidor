"""Cache de prompt do provedor — não pagar duas vezes pelo mesmo prefixo.

===========================================================================
O QUE O PROVEDOR OFERECE

Toda chamada reenvia o mesmo começo: instruções do sistema, o resumo do grafo
de memória, as definições de ferramenta. Num agente com 12 passos, esse bloco é
cobrado 12 vezes. Os provedores sabem disso e cobram bem mais barato quando
reconhecem um prefixo que já viram.

Duas famílias, e elas exigem coisas diferentes:

  - **Explícita** (Anthropic): é preciso MARCAR onde o prefixo termina, com
    `cache_control` no bloco de conteúdo. Sem a marca, não há cache.
  - **Automática** (OpenAI, DeepSeek): o provedor detecta sozinho prefixos
    repetidos acima de ~1024 tokens. Nada a fazer no pedido.

===========================================================================
A ARMADILHA QUE FAZ ISSO CUSTAR MAIS CARO

Gravar cache no Anthropic custa ~1,25x uma leitura normal; ler custa ~0,1x. A
conta só fecha se o prefixo REPETIR. Marcar um prefixo que muda a cada chamada
é pagar 1,25x para sempre e nunca acertar — a otimização vira despesa.

E prefixo instável é o caso comum sem ninguém perceber: basta a data de hoje, o
horário, um contador de mensagens ou o grafo de memória recém-atualizado
entrarem no bloco de sistema. Tudo isso parece constante e não é.

Por isso este módulo não se limita a marcar. Ele guarda a impressão digital dos
últimos prefixos e RECUSA marcar o que vem mudando — e diz por quê. Uma
otimização que não sabe dizer se está funcionando é indistinguível de um
desperdício.

===========================================================================
O QUE ELE NÃO FAZ

Não guarda resposta nenhuma. Quem faz isso é `cache_semantico.py`, que tem
riscos completamente diferentes: aqui o pior caso é gastar mais; lá o pior caso
é responder errado.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque

# Precisa de marca explícita no pedido.
_EXPLICITO = ("anthropic/", "claude")
# Faz sozinho, sem nada no pedido.
_AUTOMATICO = ("openai/", "deepseek/", "google/", "gemini", "x-ai/", "qwen/")

# Abaixo disso o provedor nem considera o prefixo, e a marca só ocupa espaço.
# É o piso da Anthropic e da OpenAI; usar o mais alto evita marcar à toa.
MIN_TOKENS = 1024

# Quantas chamadas observar antes de confiar que o prefixo é estável. Duas já
# distinguem "constante" de "muda sempre", que é a distinção que importa.
_MEMORIA = 6
_vistos: dict[str, deque] = defaultdict(lambda: deque(maxlen=_MEMORIA))


def familia(model: str) -> str:
    m = (model or "").lower()
    if any(p in m for p in _EXPLICITO):
        return "explicito"
    if any(p in m for p in _AUTOMATICO):
        return "automatico"
    return "desconhecido"


def _texto(conteudo) -> str:
    if isinstance(conteudo, str):
        return conteudo
    if isinstance(conteudo, list):
        return "".join(p.get("text", "") for p in conteudo if isinstance(p, dict))
    return ""


def _digital(mensagens: list[dict]) -> str:
    cru = json.dumps(mensagens, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(cru.encode("utf-8")).hexdigest()[:16]


def _tokens(texto: str) -> int:
    from .contexto import estima_tokens
    return estima_tokens(texto)


def estabilidade(chave: str, mensagens: list[dict]) -> tuple[bool, str]:
    """O prefixo desta origem tem se repetido?

    Devolve `(estavel, motivo)`. Na PRIMEIRA vez devolve False: ainda não há
    como saber, e marcar no escuro é exatamente o erro caro descrito no
    cabeçalho. O custo de esperar uma chamada é uma leitura normal; o custo de
    marcar errado é 25% a mais em todas.
    """
    d = _digital(mensagens)
    historico = _vistos[chave]
    historico.append(d)
    if len(historico) < 2:
        return False, "primeira chamada desta origem — ainda não dá pra saber"
    distintos = len(set(historico))
    if distintos == 1:
        return True, f"prefixo idêntico nas últimas {len(historico)} chamadas"
    return False, (f"o prefixo mudou {distintos} vez(es) nas últimas {len(historico)} "
                   "chamadas — marcar custaria mais que não marcar")


def prepara(mensagens: list[dict], model: str, *, origem: str = "chat",
            forcar: bool | None = None) -> tuple[list[dict], dict]:
    """Devolve `(mensagens, relatorio)`.

    `forcar=True` marca sem checar estabilidade (útil quando quem chama SABE
    que o prefixo é fixo). `forcar=False` nunca marca.
    """
    rel = {"familia": familia(model), "marcou": False, "motivo": "", "tokens_prefixo": 0}
    if not mensagens:
        rel["motivo"] = "sem mensagens"
        return mensagens, rel

    # O prefixo é o bloco de sistema no começo: o que de fato não muda entre as
    # voltas de um agente. Parar no primeiro não-sistema é o que garante isso.
    prefixo = []
    for m in mensagens:
        if m.get("role") != "system":
            break
        prefixo.append(m)
    if not prefixo:
        rel["motivo"] = "não há bloco de sistema para cachear"
        return mensagens, rel

    rel["tokens_prefixo"] = sum(_tokens(_texto(m.get("content"))) for m in prefixo)

    if rel["familia"] == "automatico":
        rel["motivo"] = "o provedor cacheia sozinho; nada a marcar"
        return mensagens, rel
    if rel["familia"] == "desconhecido":
        # Marcar um provedor que não entende `cache_control` pode virar erro de
        # validação. Não marcar é seguro e o pior caso é continuar como hoje.
        rel["motivo"] = "provedor sem cache conhecido"
        return mensagens, rel

    if rel["tokens_prefixo"] < MIN_TOKENS:
        rel["motivo"] = (f"prefixo de ~{rel['tokens_prefixo']} tokens é menor que o "
                         f"mínimo de {MIN_TOKENS} que o provedor cacheia")
        return mensagens, rel

    if forcar is False:
        rel["motivo"] = "desligado por quem chamou"
        return mensagens, rel
    if forcar is not True:
        estavel, motivo = estabilidade(f"{origem}|{model}", prefixo)
        if not estavel:
            rel["motivo"] = motivo
            return mensagens, rel
        rel["motivo"] = motivo

    # Marca o ÚLTIMO bloco do prefixo: o `cache_control` diz "cacheie tudo até
    # aqui", então uma marca só no fim cobre o prefixo inteiro. Marcar cada
    # mensagem gastaria os 4 pontos de quebra que a Anthropic permite sem
    # cachear nada a mais.
    saida = [dict(m) for m in mensagens]
    alvo = saida[len(prefixo) - 1]
    texto = _texto(alvo.get("content"))
    alvo["content"] = [{"type": "text", "text": texto,
                        "cache_control": {"type": "ephemeral"}}]
    rel["marcou"] = True
    return saida, rel


def esquece(chave: str | None = None) -> None:
    """Zera o que foi observado. Existe pro teste e pra quando o prompt muda de
    propósito (deploy novo), onde o histórico antigo só atrapalharia."""
    if chave is None:
        _vistos.clear()
    else:
        _vistos.pop(chave, None)
