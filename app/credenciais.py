"""Remoção de credenciais — não mandar segredo pra fora sem querer.

===========================================================================
POR QUE ISTO É NECESSÁRIO NESTE PROJETO EM PARTICULAR

O JARVIS lê arquivos da máquina do Victor e manda o conteúdo pro modelo. Um
`read_file` num `.env`, num `docker-compose.yml` ou num log de erro leva chave
de API pra dentro do prompt — e prompt vai pro provedor, entra em log, e pode
entrar em treino dependendo do contrato.

E há um precedente literal aqui: o `BACKEND_TOKEN` deste projeto já trafegou em
texto puro uma vez. O item mais urgente da lista de prioridades é rotacioná-lo.
Não é hipótese.

===========================================================================
O QUE ELE FAZ, E O TAMANHO CERTO DA AMBIÇÃO

Ele substitui o que RECONHECE por um marcador que preserva a forma. Não é
cofre, não é DLP, não pega tudo — segredo genérico é indistinguível de string
aleatória, e um detector agressivo destruiria conteúdo legítimo (hash de commit,
UUID, chave pública).

Então o alvo são os formatos com prefixo conhecido, que são justamente os que
mais vazam por descuido: `sk-`, `ghp_`, `xoxb-`, JWT, `AKIA`, e atribuição
explícita (`API_KEY=...`).

===========================================================================
POR QUE O MARCADOR PRESERVA A FORMA

Trocar por "[REMOVIDO]" cru faria o modelo perder a informação de que ali havia
uma chave — e ele passaria a inventar uma, ou a dizer que o arquivo está vazio.
`[CREDENCIAL REMOVIDA: openai_api_key]` mantém a estrutura e diz a verdade: o
campo existe, o valor não veio.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Cada par: (padrão, rótulo). O grupo 1, quando existe, é o que fica visível
# (o nome do campo); o resto é substituído.
_PADROES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), "chave_openai"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}"), "chave_anthropic"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "token_github"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"), "token_slack"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "chave_aws"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "chave_google"),
    (re.compile(r"\bey[A-Za-z0-9_\-]{10,}\.ey[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "jwt"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"),
     "chave_privada"),
    # Atribuição explícita: o nome do campo entrega o que é o valor.
    (re.compile(r"\b([A-Z_]{0,20}(?:API[_-]?KEY|SECRET|TOKEN|PASSWORD|SENHA|PASSWD|"
                r"ACCESS[_-]?KEY|PRIVATE[_-]?KEY)[A-Z_]{0,20})\s*[:=]\s*"
                r"[\"']?([^\s\"'#,;]{8,})[\"']?", re.I), "atribuicao"),
    # URL com senha embutida — vaza em log de conexão o tempo todo.
    (re.compile(r"\b([a-z][a-z0-9+.\-]*://[^\s:/@]+):([^\s:/@]{4,})@"), "url_com_senha"),
]


@dataclass
class Limpeza:
    texto: str
    achados: list[str] = field(default_factory=list)

    @property
    def limpou(self) -> bool:
        return bool(self.achados)


def _marca(rotulo: str) -> str:
    return f"[CREDENCIAL REMOVIDA: {rotulo}]"


def limpa(texto: str) -> Limpeza:
    """Substitui o que reconhece. Devolve o texto e o que foi encontrado."""
    t = str(texto or "")
    if not t:
        return Limpeza(t)
    achados: list[str] = []

    for padrao, rotulo in _PADROES:
        def troca(m: re.Match) -> str:
            if rotulo == "atribuicao":
                # Mantém o NOME do campo: perder isso faria o modelo achar que a
                # configuração não existe, em vez de existir sem o valor.
                achados.append(m.group(1).lower())
                return f"{m.group(1)}={_marca(m.group(1).lower())}"
            if rotulo == "url_com_senha":
                achados.append(rotulo)
                return f"{m.group(1)}:{_marca('senha_na_url')}@"
            achados.append(rotulo)
            return _marca(rotulo)
        t = padrao.sub(troca, t)

    return Limpeza(t, achados)


def tem_credencial(texto: str) -> bool:
    return limpa(texto).limpou
