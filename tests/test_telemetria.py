"""Telemetria de custo — o que trava aqui.

Este módulo existe para responder "para onde vão os R$ 50/mês". Ele tem duas
propriedades que, se quebrarem, o tornam pior que inútil:

  1. FALHA DE TELEMETRIA NÃO PODE DERRUBAR A CHAMADA QUE ELA MEDE. Um erro ao
     gravar métrica não pode virar "sua pergunta falhou".

  2. "DE GRAÇA" E "NÃO SEI" SÃO COISAS DIFERENTES. Ollama custa 0.0; modelo sem
     preço no catálogo custa None. Misturar os dois esconderia justamente a
     economia que o local traz — que é o motivo de tudo isto existir.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["JARVIS_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "telemetria.db")

from app import telemetria          # noqa: E402
from app.db import init_db          # noqa: E402

init_db()

falhas = []


def checa(nome, cond, detalhe=""):
    print(("  ok  " if cond else "FALHA") + "  " + nome + (f"  {detalhe}" if not cond and detalhe else ""))
    if not cond:
        falhas.append(nome)


print("— grava e agrega")
telemetria.registra(provider="openrouter", model="anthropic/claude-sonnet",
                    origem="chat", tokens_in=100, tokens_out=50,
                    custo_usd=0.0012, ms=800)
telemetria.registra(provider="ollama", model="llama3", origem="chat",
                    tokens_in=200, tokens_out=80, custo_usd=0.0, ms=150)
telemetria.registra(provider="openrouter", model="anthropic/claude-sonnet",
                    origem="agent", ms=300, ok=False, erro="timeout")

r = telemetria.resumo(dias=7)
checa("resumo responde ok", r["ok"] is True, str(r)[:120])
checa("conta as três chamadas", r["total"]["chamadas"] == 3, r["total"])
checa("soma o custo", abs(r["total"]["custo_usd"] - 0.0012) < 1e-9, r["total"])
checa("conta a falha", r["total"]["falhas"] == 1, r["total"])
checa("agrupa por modelo", len(r["por_modelo"]) == 2, r["por_modelo"])
checa("agrupa por origem", {x["origem"] for x in r["por_origem"]} == {"chat", "agent"},
      r["por_origem"])

# A janela vai na resposta: ninguém deve ler "R$ 12" sem saber de quanto tempo.
checa("declara a janela", r["dias"] == 7 and "desde_ts" in r, list(r))
# Quem exibir precisa dizer que é estimativa, senão vira número que mente.
checa("marca que o custo é estimativa", r.get("custo_e_estimativa") is True)

print("— 'de graça' e 'não sei' são diferentes")
telemetria._precos.clear()
telemetria._precos["modelo/conhecido"] = (0.000001, 0.000002)
checa("modelo com preço estima",
      telemetria.estima_custo_cache("modelo/conhecido", 1000, 1000) == 0.003,
      telemetria.estima_custo_cache("modelo/conhecido", 1000, 1000))
checa("modelo sem preço devolve None (não zero)",
      telemetria.estima_custo_cache("modelo/desconhecido", 1000, 1000) is None)
checa("sem tokens devolve None",
      telemetria.estima_custo_cache("modelo/conhecido", None, None) is None)

print("— falha de telemetria não derruba nada")
_orig = telemetria.get_conn
telemetria.get_conn = lambda: (_ for _ in ()).throw(RuntimeError("banco fora do ar"))
try:
    telemetria.registra(provider="x", model="y", origem="z")   # não pode levantar
    checa("registra engole a própria exceção", True)
except Exception as e:
    checa("registra engole a própria exceção", False, str(e))
finally:
    telemetria.get_conn = _orig

_orig2 = telemetria.get_conn
telemetria.get_conn = lambda: (_ for _ in ()).throw(RuntimeError("banco fora do ar"))
try:
    saida = telemetria.resumo(dias=7)
    checa("resumo devolve erro legível em vez de estourar", saida.get("ok") is False, saida)
finally:
    telemetria.get_conn = _orig2

print("— janela: o que é velho não entra")
import time  # noqa: E402
with telemetria.get_conn() as conn:
    conn.execute("INSERT INTO llm_calls (ts, provider, model, origem, custo_usd, ok)"
                 " VALUES (?,?,?,?,?,1)",
                 (time.time() - 40 * 86400, "openrouter", "antigo", "chat", 99.0))
r2 = telemetria.resumo(dias=7)
checa("chamada de 40 dias atrás fica fora da janela de 7",
      abs(r2["total"]["custo_usd"] - 0.0012) < 1e-9, r2["total"])
r3 = telemetria.resumo(dias=90)
checa("e aparece na janela de 90", r3["total"]["custo_usd"] > 90, r3["total"])

print()
if falhas:
    print(f"{len(falhas)} FALHA(S): " + ", ".join(falhas))
    sys.exit(1)
print("tudo passou")
