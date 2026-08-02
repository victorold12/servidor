"""Cache de resposta — não pagar de novo pela mesma pergunta.

===========================================================================
POR QUE ESTE MÓDULO É DIFERENTE DOS OUTROS DOIS DO BLOCO

`contexto.py` e `cache_prompt.py` erram pra um lado só: gastam mais que o ideal.
Este erra pro lado de **responder errado** — devolver a resposta de ontem pra
pergunta de hoje. Um assistente que erra de vez em quando com confiança é pior
que um que custa um pouco mais.

Por isso o centro deste arquivo não é o mecanismo de acerto. É a lista do que
ele SE RECUSA a cachear, e o limiar deliberadamente alto.

===========================================================================
O QUE NUNCA ENTRA NO CACHE

**Pergunta que depende de agora.** "que horas são", "o que tenho hoje", "última
mensagem". A resposta certa muda sozinha, sem ninguém mexer em nada, e o cache
não tem como saber disso.

**Pergunta sobre estado pessoal.** "meus arquivos", "minha agenda", "quanto
gastei". O mundo muda entre uma pergunta e outra.

**Pergunta com ferramenta.** Se o modelo ia agir, a ação precisa acontecer.
Devolver do cache o texto de uma ação que não foi executada é a falha mais
perigosa possível aqui — dizer "pronto, apaguei" sem ter apagado.

**Contexto diferente.** Mesma pergunta com outro prompt de sistema, outro
histórico ou outro modelo é outra pergunta. Por isso a chave inclui a impressão
digital do contexto, e não só o texto.

===========================================================================
COMO ELE DECIDE QUE DUAS PERGUNTAS SÃO A MESMA

Em duas camadas, da mais segura pra menos:

1. **Igualdade normalizada** — mesma pergunta com outra caixa, acento ou
   espaçamento. Risco praticamente zero, e é a maioria dos acertos reais:
   gente repete pergunta muito mais do que parafraseia.
2. **Semelhança léxica alta** (Jaccard sobre palavras de conteúdo), com limiar
   de 0,92. É proposital que quase nada passe: o ganho de cachear parafrase é
   pequeno e o risco é grande.

Embeddings ficaram de fora de propósito. Semelhança vetorial acha "capital da
França" parecida com "capital da Itália" — parecidas em forma, opostas em
resposta. Sem um jeito barato de medir a taxa de erro dessa camada, ela é risco
sem medição, e este projeto já decidiu que "existe" e "funciona" divergem.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field

# Limiar alto de propósito — ver o cabeçalho.
LIMIAR_PADRAO = 0.92
TTL_PADRAO_S = 3600
TAMANHO_MAX = 300

# Pergunta cuja resposta certa muda sozinha. Não é lista de palavras proibidas:
# é lista de sinais de que a resposta tem prazo de validade.
_DEPENDE_DE_AGORA = re.compile(
    r"\b(agora|hoje|amanh[ãa]|ontem|neste momento|atualmente|no momento|"
    r"que horas|que dia|esta semana|este m[êe]s|este ano|"
    r"[úu]ltim[ao]s?|recente|mais novo|ainda|j[áa] )\b", re.I)

# Pergunta sobre o estado do usuário ou da máquina.
_DEPENDE_DE_ESTADO = re.compile(
    r"\b(meu|meus|minha|minhas|eu tenho|tenho \w+ (hoje|agora)|"
    r"minha agenda|meus arquivos|meus e-?mails?|quanto (gastei|custou|sobrou)|"
    r"saldo|pendente|caixa de entrada)\b", re.I)

_PALAVRAS_VAZIAS = {
    "a", "o", "as", "os", "um", "uma", "de", "do", "da", "dos", "das", "em",
    "no", "na", "nos", "nas", "por", "para", "pra", "com", "sem", "que", "e",
    "ou", "se", "me", "qual", "quais", "como", "quanto", "quem", "onde", "é",
    "eh", "ser", "esta", "este", "isso", "isto", "ao", "aos", "à", "às",
}


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def normaliza(texto: str) -> str:
    t = _sem_acento(str(texto or "")).lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _palavras(texto: str) -> set[str]:
    return {p for p in normaliza(texto).split() if p not in _PALAVRAS_VAZIAS and len(p) > 1}


def semelhanca(a: str, b: str) -> float:
    """Jaccard sobre palavras de conteúdo. 1.0 = mesmas palavras."""
    pa, pb = _palavras(a), _palavras(b)
    if not pa or not pb:
        return 0.0
    return len(pa & pb) / len(pa | pb)


def cacheavel(pergunta: str, *, tem_ferramentas: bool = False) -> tuple[bool, str]:
    """Esta pergunta PODE ser respondida do cache?

    Devolve `(pode, motivo)`. O motivo existe pra o log poder explicar por que o
    cache não ajudou — sem ele, "o cache nunca acerta" vira mistério.
    """
    if tem_ferramentas:
        # Devolver do cache o texto de uma ação que não foi executada é a falha
        # mais perigosa deste módulo: "pronto, apaguei" sem ter apagado.
        return False, "a pergunta pode disparar ação; o cache não executa nada"
    t = str(pergunta or "").strip()
    if len(t) < 8:
        return False, "curta demais pra identificar com segurança"
    if len(t) > 4000:
        return False, "longa demais: provavelmente carrega contexto próprio"
    if _DEPENDE_DE_AGORA.search(t):
        return False, "a resposta muda com o tempo"
    if _DEPENDE_DE_ESTADO.search(t):
        return False, "a resposta depende do estado pessoal, que muda sozinho"
    return True, ""


def digital_contexto(mensagens: list[dict] | None, model: str = "") -> str:
    """Mesma pergunta com outro sistema, outro histórico ou outro modelo é OUTRA
    pergunta. Sem isto, o cache vazaria resposta entre conversas."""
    base = [m for m in (mensagens or []) if m.get("role") != "user"]
    cru = json.dumps([base, model], ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(cru.encode("utf-8")).hexdigest()[:16]


@dataclass
class Entrada:
    pergunta: str
    resposta: str
    contexto: str
    quando: float
    usos: int = 0


@dataclass
class Cache:
    ttl_s: float = TTL_PADRAO_S
    limiar: float = LIMIAR_PADRAO
    tamanho_max: int = TAMANHO_MAX
    _itens: list[Entrada] = field(default_factory=list)
    acertos: int = 0
    erros: int = 0
    recusas: int = 0

    def _limpa(self) -> None:
        agora = time.time()
        self._itens = [e for e in self._itens if agora - e.quando < self.ttl_s]
        if len(self._itens) > self.tamanho_max:
            # Descarta o mais antigo. Não é LRU sofisticado de propósito: com
            # 300 entradas e TTL de 1h, a diferença é irrelevante e a política
            # simples é a que se consegue auditar.
            self._itens = self._itens[-self.tamanho_max:]

    def consulta(self, pergunta: str, *, contexto: str = "",
                 tem_ferramentas: bool = False) -> tuple[str | None, str]:
        """Devolve `(resposta_ou_None, motivo)`."""
        pode, motivo = cacheavel(pergunta, tem_ferramentas=tem_ferramentas)
        if not pode:
            self.recusas += 1
            return None, motivo
        self._limpa()

        alvo = normaliza(pergunta)
        # Camada 1: igualdade normalizada. É a maioria dos acertos reais e a de
        # risco praticamente zero.
        for e in reversed(self._itens):
            if e.contexto == contexto and normaliza(e.pergunta) == alvo:
                e.usos += 1
                self.acertos += 1
                return e.resposta, "pergunta idêntica"

        # Camada 2: semelhança alta. Quase nada passa, e isso é o desenho.
        melhor, escore = None, 0.0
        for e in self._itens:
            if e.contexto != contexto:
                continue
            s = semelhanca(pergunta, e.pergunta)
            if s > escore:
                melhor, escore = e, s
        if melhor is not None and escore >= self.limiar:
            melhor.usos += 1
            self.acertos += 1
            return melhor.resposta, f"semelhança {escore:.2f}"

        self.erros += 1
        return None, "nada parecido o bastante"

    def guarda(self, pergunta: str, resposta: str, *, contexto: str = "",
               tem_ferramentas: bool = False) -> bool:
        pode, _ = cacheavel(pergunta, tem_ferramentas=tem_ferramentas)
        if not pode or not str(resposta or "").strip():
            return False
        self._itens.append(Entrada(pergunta, resposta, contexto, time.time()))
        # Poda DEPOIS de inserir. Podar antes deixava sempre uma entrada a mais
        # que o teto — o teto valia pro estado anterior, não pro resultado.
        self._limpa()
        return True

    def resumo(self) -> dict:
        total = self.acertos + self.erros
        return {
            "entradas": len(self._itens),
            "acertos": self.acertos,
            "erros": self.erros,
            "recusas": self.recusas,
            # Taxa sobre o que foi CONSULTADO de verdade. Incluir as recusas
            # afundaria o número e faria parecer quebrado o que está sendo
            # prudente.
            "taxa": round(self.acertos / total, 3) if total else None,
        }

    def esvazia(self) -> None:
        self._itens.clear()
        self.acertos = self.erros = self.recusas = 0


# Instância única do processo. Memória, não disco: no Render o container é
# recriado a cada deploy e a cada volta de hibernação, então persistir daria
# trabalho pra guardar o que some sozinho.
cache = Cache()
