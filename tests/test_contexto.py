"""Compressão de contexto.

O QUE ESTE TESTE PROTEGE

Antes de economizar, não quebrar. Uma compressão que produz histórico inválido
troca uma conta alta por um erro 400 no meio de uma tarefa longa — e a tarefa
longa é justamente a cara, então o prejuízo dobra.

O caso central é o pareamento `tool_call` / `tool`. O provedor RECUSA uma
mensagem `role="tool"` que não venha logo depois do assistente que pediu aquela
ferramenta. Cortar por mensagem, e não por turno, produz exatamente isso.

Depois disso: não tocar no sistema, não tocar no recente, e nunca comprimir em
silêncio.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.contexto import (  # noqa: E402
    agrupa, comprime, estima_tokens,
)

falhas = []


def checa(nome, cond, detalhe=""):
    print(("  ok  " if cond else "FALHA") + "  " + nome + (f"  {detalhe}" if not cond and detalhe else ""))
    if not cond:
        falhas.append(nome)


def conversa(n_passos, tamanho_obs=6000):
    """Imita o agente autônomo: assistente pede ferramenta, ferramenta responde."""
    msgs = [{"role": "system", "content": "Você é o JARVIS."},
            {"role": "user", "content": "Analise os arquivos do projeto."}]
    for i in range(n_passos):
        msgs.append({"role": "assistant", "content": None,
                     "tool_calls": [{"id": f"c{i}", "type": "function",
                                     "function": {"name": "read_file",
                                                  "arguments": '{"path":"x.py"}'}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}",
                     "content": f"conteudo do passo {i} " + "L" * tamanho_obs})
    return msgs


def orfaos(msgs):
    """Toda mensagem `tool` tem um assistente com o mesmo id logo antes?"""
    problemas = []
    for i, m in enumerate(msgs):
        if m.get("role") != "tool":
            continue
        tid = m.get("tool_call_id")
        # Procura pra trás até o assistente mais próximo.
        dono = None
        for ant in reversed(msgs[:i]):
            if ant.get("role") == "assistant":
                dono = ant
                break
            if ant.get("role") != "tool":
                break
        ids = {c.get("id") for c in (dono or {}).get("tool_calls") or []}
        if tid not in ids:
            problemas.append(tid)
    return problemas


print("— o que não precisa comprimir passa intacto")
curta = [{"role": "system", "content": "s"}, {"role": "user", "content": "oi"}]
saida, rel = comprime(curta, teto_tokens=100000)
checa("devolve as mesmas mensagens", saida == curta)
checa("e diz que não comprimiu", rel.comprimiu is False, rel)

print("— A ARMADILHA: nenhuma resposta de ferramenta fica órfã")
msgs = conversa(14)
checa("a conversa de origem é válida", orfaos(msgs) == [], orfaos(msgs))
saida, rel = comprime(msgs, teto_tokens=3000)
checa("comprimiu de verdade", rel.comprimiu is True, rel)
checa("e continua válida", orfaos(saida) == [], orfaos(saida))
checa("cabe no teto", estima_tokens(saida) <= 3000, estima_tokens(saida))

print("— corta em turnos inteiros, nunca pela metade")
ids_assistente = {c["id"] for m in saida if m.get("role") == "assistant"
                  for c in (m.get("tool_calls") or [])}
ids_ferramenta = {m["tool_call_id"] for m in saida if m.get("role") == "tool"}
checa("todo id de ferramenta tem assistente correspondente",
      ids_ferramenta <= ids_assistente, ids_ferramenta - ids_assistente)

print("— a mensagem de sistema é intocável")
checa("continua em primeiro", saida[0].get("role") == "system", saida[0])
checa("com o conteúdo original", saida[0]["content"] == "Você é o JARVIS.", saida[0])

print("— o recente é preservado")
saida, rel = comprime(conversa(20), teto_tokens=4000, manter_recentes=4)
ultimas = [m.get("content") for m in saida[-2:]]
checa("a última observação está inteira",
      any("passo 19" in str(c) for c in ultimas), ultimas)
checa("e não foi encurtada",
      not any("omitidos pela compressão" in str(c) for c in ultimas), ultimas)

print("— a janela recente maior que o teto NÃO é devolvida em silêncio")
# O caso que expôs o buraco: com 6 observações recentes de 6000 caracteres, a
# janela sozinha passava do teto e a primeira versão devolvia acima do
# orçamento afirmando ter comprimido.
saida, rel = comprime(conversa(14), teto_tokens=3000, manter_recentes=6)
checa("cabe mesmo com janela grande", estima_tokens(saida) <= 3000, estima_tokens(saida))
checa("e declara que coube", rel.coube is True, rel)
# O último turno é o que está sendo resolvido: nunca encurtado.
checa("o último turno fica inteiro",
      "omitidos pela compressão" not in str(saida[-1].get("content") or ""), saida[-1])

print("— o teto é contrato; manter_recentes é preferência")
# Pediu 6 recentes num teto que não comporta 6: a preferência cede, não o teto.
saida, rel = comprime(conversa(14), teto_tokens=2000, manter_recentes=6)
checa("o teto vence a preferência", estima_tokens(saida) <= 2000, estima_tokens(saida))
checa("e ainda é histórico válido", orfaos(saida) == [], orfaos(saida))

print("— quando é fisicamente impossível, DIZ que é")
# O último turno sozinho estoura: não há corte que resolva, e mentir aqui faria
# quem chamou confiar num teto que não vale.
saida, rel = comprime(conversa(3, tamanho_obs=40000), teto_tokens=500)
checa("admite que não coube", rel.coube is False, rel)
checa("mas devolve algo utilizável", orfaos(saida) == [], orfaos(saida))
checa("e o aviso aparece no texto do relatório", "acima do teto" in str(rel), str(rel))

print("— encurtar observação vem ANTES de descartar turno")
# Encurtar dana menos que descartar, então todo o encurtamento vem primeiro.
saida, rel = comprime(conversa(8), teto_tokens=6000)
checa("encurtou observações", rel.ferramentas_encurtadas > 0, rel)
checa("sem descartar nada", rel.turnos_descartados == 0, rel)
checa("todos os passos continuam presentes",
      all(any(f"passo {i}" in str(m.get("content") or "") for m in saida)
          for i in range(8)), "perdeu passo")

print("— o que foi encurtado avisa que foi")
encurtadas = [m for m in saida if "omitidos pela compressão" in str(m.get("content") or "")]
checa("marca o corte no texto", len(encurtadas) > 0)
checa("preserva o começo", any(str(m["content"]).startswith("conteudo do passo")
                               for m in encurtadas), encurtadas[:1])

print("— descarte silencioso não existe")
saida, rel = comprime(conversa(30), teto_tokens=2500)
checa("descartou turnos", rel.turnos_descartados > 0, rel)
aviso = [m for m in saida if "removidos para caber no contexto" in str(m.get("content") or "")]
checa("deixou aviso no lugar", len(aviso) == 1, len(aviso))
checa("e o aviso manda NÃO supor", "em vez de supor" in aviso[0]["content"], aviso[0])

print("— com resumidor, o trecho vira resumo")
saida, rel = comprime(conversa(30), teto_tokens=2500,
                      resumidor=lambda ms: f"resumo de {len(ms)} mensagens")
checa("usou o resumidor", rel.resumiu is True, rel)
resumo = [m for m in saida if "resumo do trecho anterior" in str(m.get("content") or "")]
checa("o resumo entrou", len(resumo) == 1, len(resumo))
checa("com o texto do resumidor", "resumo de" in resumo[0]["content"], resumo[0])

print("— resumidor que FALHA não derruba a conversa")
saida, rel = comprime(conversa(30), teto_tokens=2500,
                      resumidor=lambda ms: (_ for _ in ()).throw(RuntimeError("caiu")))
checa("não estourou", isinstance(saida, list))
checa("caiu no aviso", any("removidos para caber" in str(m.get("content") or "")
                           for m in saida))
checa("e diz que não resumiu", rel.resumiu is False, rel)
# Uma tarefa longa morrer por causa da OTIMIZAÇÃO seria o pior desfecho.
checa("o histórico continua válido", orfaos(saida) == [], orfaos(saida))

print("— o relatório é legível por quem paga a conta")
checa("mostra antes e depois", "->" in str(rel), str(rel))
checa("mede economia", rel.economia > 0, rel.economia)

print("— agrupamento")
t = agrupa(conversa(3))
checa("um turno por assistente+ferramentas", len(t) == 2 + 3, len(t))
checa("o turno de ferramenta tem duas mensagens",
      all(len(x.mensagens) == 2 for x in t[2:]), [len(x.mensagens) for x in t])

print("— tool sem dono não some")
soltas = [{"role": "tool", "tool_call_id": "z", "content": "orfa"}]
checa("vira turno próprio", len(agrupa(soltas)) == 1,
      "perder mensagem calada seria trocar um defeito por outro pior")

print("— estimativa de tokens")
checa("texto vazio é ~0", estima_tokens("") <= 1)
checa("None não estoura", estima_tokens(None) == 0)
checa("tool_calls contam", estima_tokens({"role": "assistant", "content": None,
      "tool_calls": [{"id": "x", "function": {"name": "f", "arguments": "{}" * 50}}]}) > 20)
checa("cresce com o tamanho", estima_tokens("a" * 4000) > estima_tokens("a" * 400))

# ---------------------------------------------------------------------------
# LIGAÇÃO COM O PRODUTO
#
# Um compressor perfeito que ninguém chama economiza zero. Esta conferência
# custa uma leitura de arquivo e evita a classe inteira de "módulo órfão" —
# a mesma que deixou o 41-matematica.js meses fora do bundle.
import pathlib  # noqa: E402

_raiz = pathlib.Path(__file__).resolve().parent.parent
_auto = (_raiz / "app" / "routers" / "autonomous.py").read_text(encoding="utf-8")
print("— o agente autônomo de fato comprime")
checa("importa o compressor", "from ..contexto import comprime" in _auto)
checa("chama dentro do laço", "comprime(messages, teto_tokens=" in _auto)
checa("e avisa quando comprimiu", 'sse("contexto"' in _auto,
      "comprimir em silêncio esconderia a causa de uma resposta pior")

print()
if falhas:
    print(f"{len(falhas)} FALHA(S): " + ", ".join(falhas))
    sys.exit(1)
print("tudo passou")
