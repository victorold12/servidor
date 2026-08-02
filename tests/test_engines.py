"""Contrato de engine.

Desacopla QUAL modelo responde de QUEM pediu. Até aqui o OpenRouter estava
cravado: acrescentar provedor significava mexer em quem chama, não em quem
implementa.

O que fica travado:
  - ausência de Ollama é estado NORMAL, não erro
  - `escolhe` nunca devolve None (sem engine não há o que responder)
  - preferência inexistente NÃO derruba — cai no disponível
  - local vem primeiro na ordem de preferência (a tese do projeto)
  - `de_graca` distingue local de nuvem, que é a base da economia
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import engines            # noqa: E402
from app.config import settings    # noqa: E402

falhas = []


def checa(nome, cond, detalhe=""):
    print(("  ok  " if cond else "FALHA") + "  " + nome + (f"  {detalhe}" if not cond and detalhe else ""))
    if not cond:
        falhas.append(nome)


# Estado real da instalação, restaurado no fim.
_base, _model = settings.ollama_base, settings.ollama_model

print("— sem Ollama configurado (a instalação mais comum)")
settings.ollama_base, settings.ollama_model = "", ""
checa("ollama devolve None, não exceção", engines.por_nome("ollama") is None)
lista = engines.disponiveis()
checa("sobra o OpenRouter", [e.nome for e in lista] == ["openrouter"], [e.nome for e in lista])
checa("escolhe nunca devolve None", engines.escolhe() is not None)
# Pedir Ollama numa máquina sem Ollama deve RESPONDER pela nuvem, não falhar:
# quem chama descobre quem respondeu pelo `_provider`, que já é o contrato.
checa("pedir ollama sem ollama cai na nuvem", engines.escolhe("ollama").nome == "openrouter")
checa("nuvem custa", engines.escolhe().custa is True)
checa("e não é de graça", engines.escolhe().de_graca is False)
r = engines.resumo()
checa("resumo diz que não tem local", r["tem_local"] is False, r)

print("— com Ollama configurado")
settings.ollama_base, settings.ollama_model = "http://127.0.0.1:11434/v1", "llama3"
lista = engines.disponiveis()
# Local primeiro é a tese adotada: local por padrão, nuvem quando necessário.
checa("local vem primeiro", [e.nome for e in lista] == ["ollama", "openrouter"],
      [e.nome for e in lista])
checa("escolhe sem preferência pega o local", engines.escolhe().nome == "ollama")
checa("local não custa", engines.escolhe().custa is False)
checa("local é de graça", engines.escolhe().de_graca is True)
checa("local é local", engines.escolhe().local is True)
checa("dá pra pedir a nuvem pelo nome", engines.escolhe("openrouter").nome == "openrouter")
r = engines.resumo()
checa("resumo diz que tem local", r["tem_local"] is True, r)
checa("e qual é o padrão", r["padrao"] == "ollama", r)

print("— barra no fim não vira URL dupla")
settings.ollama_base = "http://127.0.0.1:11434/v1/"
checa("base normalizada", engines.escolhe().base == "http://127.0.0.1:11434/v1",
      engines.escolhe().base)

print("— modelo explícito")
settings.ollama_base, settings.ollama_model = "", ""
e = engines.escolhe(model="anthropic/claude-sonnet")
# Nome de modelo sem preferência de engine é catálogo do OpenRouter na
# esmagadora maioria dos casos.
checa("modelo sem engine vai pra nuvem", e.nome == "openrouter", e)
checa("e respeita o modelo pedido", e.model == "anthropic/claude-sonnet", e)

print("— o Engine é imutável")
try:
    engines.escolhe().nome = "outro"          # type: ignore[misc]
    checa("não dá pra alterar um Engine", False, "mutação passou")
except Exception:
    # frozen: um engine passado adiante não pode ser modificado por quem recebeu
    checa("não dá pra alterar um Engine", True)

settings.ollama_base, settings.ollama_model = _base, _model

print()
if falhas:
    print(f"{len(falhas)} FALHA(S): " + ", ".join(falhas))
    sys.exit(1)
print("tudo passou")
