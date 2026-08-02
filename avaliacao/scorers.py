"""Os julgadores. Cada um olha uma saída e diz passou, falhou, ou NÃO SEI.

===========================================================================
A REGRA QUE DEFINE ESTE ARQUIVO

"Não consegui julgar" é um terceiro resultado, e ele NUNCA conta como aprovação.

É a mesma disciplina do resto do projeto, na terceira encarnação:
`telemetria.py` separa "de graça" (0.0) de "não sei" (None); `ollama.js` separa
"nada carregado" ([]) de "não deu pra consultar"; aqui `passou=None` é distinto
de `passou=True`.

O motivo é sempre o mesmo. Um arnês existe pra dizer se o sistema piorou, e um
julgador que devolve verde quando não conseguiu olhar produz exatamente a
mentira mais cara possível: a confiança de que nada quebrou.

===========================================================================
POR QUE OS DETERMINÍSTICOS VÊM PRIMEIRO

Julgar com LLM custa dinheiro e varia entre execuções — as duas coisas que um
arnês menos pode ter. A maior parte do que importa aqui é verificável sem
modelo nenhum: qual engine foi escolhido, se a resposta cita a fonte, se o texto
que vai pra voz tem asterisco, quanto custou, quanto demorou.

O juiz por LLM existe (`juiz`), mas é opt-in e cobra: quem chama tem que passar
uma função de julgamento e aceitar o custo.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


@dataclass
class Nota:
    """`passou=None` significa NÃO SEI. Ver o cabeçalho: não é aprovação."""
    passou: bool | None
    detalhe: str = ""
    criterio: str = ""


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def _normaliza(s: str) -> str:
    """Compara por conteúdo, não por digitação: minúsculas, sem acento, espaço
    colapsado. Reprovar "São Paulo" contra "sao paulo" seria medir teclado."""
    return re.sub(r"\s+", " ", _sem_acento(str(s or "")).lower()).strip()


# ---------------------------------------------------------------------------
# Julgadores de TEXTO

def contem(saida: str, valor, **_) -> Nota:
    """Todos os termos precisam aparecer. Lista = conjunção, de propósito:
    "cite o ano E o nome" é um critério só, e passar meio não é passar."""
    termos = valor if isinstance(valor, list) else [valor]
    alvo = _normaliza(saida)
    faltando = [t for t in termos if _normaliza(t) not in alvo]
    if faltando:
        return Nota(False, f"faltou: {', '.join(map(str, faltando))}")
    return Nota(True)


def nao_contem(saida: str, valor, **_) -> Nota:
    termos = valor if isinstance(valor, list) else [valor]
    alvo = _normaliza(saida)
    achados = [t for t in termos if _normaliza(t) in alvo]
    if achados:
        return Nota(False, f"apareceu (não devia): {', '.join(map(str, achados))}")
    return Nota(True)


def regex(saida: str, valor, **_) -> Nota:
    try:
        padrao = re.compile(str(valor), re.I | re.M)
    except re.error as e:
        # Critério quebrado é problema DO CASO, não do sistema medido. Reprovar
        # o sistema aqui culparia o inocente.
        return Nota(None, f"regex inválida no caso: {e}")
    return Nota(bool(padrao.search(str(saida or ""))), f"não casou: {valor}")


def nao_vazio(saida: str, valor=None, **_) -> Nota:
    """Existe porque "não quebrou" e "respondeu" divergem: um modelo que devolve
    string vazia passa em todo critério de `nao_contem`."""
    return Nota(bool(str(saida or "").strip()), "resposta vazia")


# ---------------------------------------------------------------------------
# Julgador da FALA
#
# O JARVIS lê a resposta em voz alta. Marcação que a tela renderiza, a voz
# SOLETRA: "asterisco asterisco importante". Isto já foi defeito reclamado, e o
# `fala-natural.js` resolve — mas só continua resolvido se alguém medir.

_MARCAS_FALADAS = [
    (r"\*{1,3}\w", "asterisco de negrito/itálico"),
    (r"^#{1,6}\s", "cerquilha de título"),
    (r"`{1,3}", "crase de código"),
    (r"\[[^\]]+\]\([^)]+\)", "link em markdown"),
    (r"https?://", "URL crua"),
    (r"[\U0001F300-\U0001FAFF☀-➿]", "emoji"),
    (r"^\s*[-*+]\s", "marcador de lista"),
    (r"\|.*\|", "tabela"),
]


def sem_marcacao(saida: str, valor=None, **_) -> Nota:
    """Nada que a voz soletraria pode sobrar."""
    texto = str(saida or "")
    achados = [nome for padrao, nome in _MARCAS_FALADAS
               if re.search(padrao, texto, re.M)]
    if achados:
        return Nota(False, "a voz soletraria: " + ", ".join(achados))
    return Nota(True)


# ---------------------------------------------------------------------------
# Julgadores de COMPORTAMENTO
#
# Não olham o texto: olham a decisão. São os mais baratos e os que mais pegam
# regressão, porque a decisão errada é sistemática e o texto ruim é aleatório.

def engine(saida, valor, meta: dict | None = None, **_) -> Nota:
    """Qual motor atendeu. Para casos de roteamento."""
    real = (meta or {}).get("engine")
    if real is None:
        return Nota(None, "a execução não registrou o engine")
    return Nota(real == valor, f"esperava {valor}, veio {real}")


def desempatar(saida, valor, meta: dict | None = None, **_) -> Nota:
    """A heurística admitiu dúvida? Zona cinzenta é informação, não defeito —
    o que seria defeito é ela fingir convicção."""
    real = (meta or {}).get("desempatar")
    if real is None:
        return Nota(None, "a execução não registrou desempate")
    return Nota(bool(real) == bool(valor), f"esperava desempatar={valor}, veio {real}")


def ate_ms(saida, valor, meta: dict | None = None, **_) -> Nota:
    real = (meta or {}).get("ms")
    if real is None:
        return Nota(None, "a execução não registrou latência")
    return Nota(real <= float(valor), f"{real}ms > teto de {valor}ms")


def ate_usd(saida, valor, meta: dict | None = None, **_) -> Nota:
    """Teto de custo POR PERGUNTA. O orçamento do projeto é R$ 50/mês; uma
    resposta que custa dez vezes o esperado é regressão mesmo estando certa."""
    real = (meta or {}).get("custo_usd")
    if real is None:
        # Custo desconhecido não é custo zero — ver telemetria.py.
        return Nota(None, "custo desconhecido")
    return Nota(real <= float(valor), f"US$ {real:.6f} > teto de US$ {float(valor):.6f}")


# ---------------------------------------------------------------------------
# Juiz por LLM — opt-in, porque cobra

def juiz(saida, valor, julgador=None, entrada: str = "", **_) -> Nota:
    """Pergunta a um modelo se a resposta satisfaz o critério em `valor`.

    Sem `julgador` devolve NÃO SEI em vez de passar: rodar o arnês sem juiz
    configurado é comum (é o modo grátis), e converter isso em verde faria a
    execução barata parecer melhor que a cara.
    """
    if julgador is None:
        return Nota(None, "sem juiz configurado (execução sem custo)")
    try:
        veredito, motivo = julgador(entrada=entrada, saida=saida, criterio=valor)
    except Exception as e:
        return Nota(None, f"o juiz falhou: {str(e)[:80]}")
    return Nota(bool(veredito), motivo or "")


SCORERS = {
    "contem": contem,
    "nao_contem": nao_contem,
    "regex": regex,
    "nao_vazio": nao_vazio,
    "sem_marcacao": sem_marcacao,
    "engine": engine,
    "desempatar": desempatar,
    "ate_ms": ate_ms,
    "ate_usd": ate_usd,
    "juiz": juiz,
}


def aplica(criterio: dict, saida: str, meta: dict | None = None,
           entrada: str = "", julgador=None) -> Nota:
    """Roda um critério. Tipo desconhecido é NÃO SEI, nunca aprovação —
    um `.jsonl` com typo silenciosamente virando verde é o pior modo de falha
    possível pra um arnês."""
    tipo = criterio.get("tipo")
    fn = SCORERS.get(tipo)
    if fn is None:
        return Nota(None, f"critério desconhecido: {tipo!r}", criterio=str(tipo))
    nota = fn(saida, criterio.get("valor"), meta=meta, entrada=entrada, julgador=julgador)
    nota.criterio = tipo
    return nota


def veredito(notas: list[Nota]) -> bool | None:
    """Um caso passa quando TODOS os critérios passam.

    Qualquer indefinido derruba pra indefinido — nunca pra verde. Uma falha
    ganha de tudo: saber que quebrou é mais útil que saber que não deu pra
    julgar o resto.
    """
    if not notas:
        return None
    if any(n.passou is False for n in notas):
        return False
    if any(n.passou is None for n in notas):
        return None
    return True
