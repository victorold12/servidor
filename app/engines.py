"""Contrato de engine — desacopla QUAL modelo responde de QUEM pediu.

===========================================================================
POR QUE ESTE MÓDULO EXISTE

Até aqui o OpenRouter estava cravado: todo chamador do backend sabia que existe
OpenRouter. Acrescentar um provedor significava mexer em quem chama, não em quem
implementa — acoplamento clássico entre política e mecanismo.

O `openrouter.py` já tinha o embrião certo: um fallback para Ollama com
`_provider` marcado na resposta. Mas fallback é rede de segurança, não escolha:
o local só entrava quando a nuvem falhava. Este módulo transforma isso em
ESCOLHA, que é o que permite o roteador dizer "esta pergunta é simples, resolve
local" e economizar de verdade.

===========================================================================
A DECISÃO DE DESENHO: FORMATO OPENAI COMO REFERÊNCIA

Um contrato, N implementações, todas falando o formato da OpenAI. Suportar um
provedor novo passa a custar um adaptador em vez de espalhar `if` pelo código.

Isso não é teoria — o projeto já provou que funciona em outro lugar: o
`agente-local/src/tts.js` fala com Chatterbox E Kokoro com um cliente só, porque
os dois expõem `POST /v1/audio/speech`. A degradação automática entre eles saiu
de graça. Aqui é o mesmo raciocínio aplicado a modelos de texto.

===========================================================================
O QUE ESTE MÓDULO NÃO FAZ

Não decide QUAL engine usar — isso é roteamento, e mora em `router_llm.py`.
Aqui só se responde "quais existem, e como falo com cada um". Misturar as duas
coisas foi a tentação óbvia e produziria um módulo que ninguém consegue testar
sem rede.
"""
from dataclasses import dataclass

from .config import settings


@dataclass(frozen=True)
class Engine:
    """Um lugar onde se pode pedir uma resposta.

    `base` e `model` bastam porque todos falam o formato da OpenAI. Se um dia
    entrar um provedor que não fala, ele ganha um adaptador que traduz — e não
    um campo novo aqui.
    """
    nome: str          # "openrouter" | "ollama" | ...
    base: str          # raiz da API, sem barra no fim
    model: str         # modelo padrão deste engine
    local: bool        # roda na máquina do usuário?
    custa: bool        # consome orçamento?

    @property
    def de_graca(self) -> bool:
        return not self.custa


def _openrouter(model: str | None = None) -> Engine:
    return Engine(
        nome="openrouter",
        base=settings.openrouter_base.rstrip("/"),
        model=model or settings.default_model,
        local=False,
        custa=True,
    )


def _ollama(model: str | None = None) -> Engine | None:
    """None quando não está configurado — ausência é estado NORMAL, não erro.

    A maioria das instalações não tem Ollama. Levantar exceção aqui obrigaria
    todo chamador a tratar, e o tratamento correto é sempre o mesmo: seguir sem.
    """
    if not (settings.ollama_base and settings.ollama_model):
        return None
    return Engine(
        nome="ollama",
        base=settings.ollama_base.rstrip("/"),
        model=model or settings.ollama_model,
        local=True,
        custa=False,
    )


def disponiveis() -> list[Engine]:
    """Quais engines existem AGORA, nesta instalação.

    Locais primeiro: a ordem é a preferência quando ninguém especificou, e a
    tese que este projeto adotou é local por padrão, nuvem quando necessário.
    Quem quer o contrário pede pelo nome.
    """
    lista: list[Engine] = []
    local = _ollama()
    if local:
        lista.append(local)
    lista.append(_openrouter())
    return lista


def por_nome(nome: str, model: str | None = None) -> Engine | None:
    if nome == "openrouter":
        return _openrouter(model)
    if nome == "ollama":
        return _ollama(model)
    return None


def escolhe(preferencia: str | None = None, model: str | None = None) -> Engine:
    """O engine a usar. Nunca devolve None — sem engine não há o que responder,
    e devolver None empurraria a decisão pra quem não tem informação pra tomá-la.

    Sem preferência, o primeiro disponível. Preferência que não existe cai no
    primeiro disponível TAMBÉM, e de propósito: pedir Ollama numa máquina sem
    Ollama deve responder pela nuvem, não falhar. O chamador descobre quem
    respondeu pelo `_provider` da resposta, que já é o contrato de hoje.
    """
    if preferencia:
        alvo = por_nome(preferencia, model)
        if alvo:
            return alvo
    if model:
        # Modelo explícito sem preferência de engine: é nome de catálogo do
        # OpenRouter na esmagadora maioria dos casos.
        return _openrouter(model)
    return disponiveis()[0]


def resumo() -> dict:
    """Para o /api/health e o painel dizerem o que a instalação consegue."""
    lista = disponiveis()
    return {
        "engines": [
            {"nome": e.nome, "model": e.model, "local": e.local, "de_graca": e.de_graca}
            for e in lista
        ],
        "tem_local": any(e.local for e in lista),
        "padrao": lista[0].nome,
    }
