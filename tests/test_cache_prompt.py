"""Cache de prompt do provedor.

O QUE ESTE TESTE PROTEGE

A propriedade que separa economia de desperdício: **só marcar o que repete**.

Gravar cache custa ~1,25x uma leitura normal; ler custa ~0,1x. Marcar um
prefixo que muda a cada chamada é pagar 25% a mais para sempre e nunca acertar.
E prefixo instável é o caso comum sem ninguém perceber — basta uma data, um
horário ou o grafo de memória recém-atualizado entrarem no bloco de sistema.

Por isso o caso central aqui não é "marcou": é "NÃO marcou quando não devia".
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import cache_prompt as cp  # noqa: E402

falhas = []


def checa(nome, cond, detalhe=""):
    print(("  ok  " if cond else "FALHA") + "  " + nome + (f"  {detalhe}" if not cond and detalhe else ""))
    if not cond:
        falhas.append(nome)


GRANDE = "instruções do sistema. " * 400          # bem acima do mínimo
def msgs(sistema=GRANDE, pergunta="oi"):
    return [{"role": "system", "content": sistema},
            {"role": "user", "content": pergunta}]


print("— famílias de provedor")
checa("anthropic precisa de marca", cp.familia("anthropic/claude-sonnet-4") == "explicito")
checa("openai cacheia sozinho", cp.familia("openai/gpt-4.1-mini") == "automatico")
checa("deepseek também", cp.familia("deepseek/deepseek-chat") == "automatico")
checa("desconhecido é desconhecido", cp.familia("fabricante-novo/modelo-x") == "desconhecido")

print("— NUNCA marca na primeira chamada")
# Marcar no escuro é o erro caro: custa 25% a mais e pode nunca ser lido.
cp.esquece()
_, rel = cp.prepara(msgs(), "anthropic/claude-sonnet-4")
checa("primeira chamada não marca", rel["marcou"] is False, rel)
checa("e explica que ainda não dá pra saber", "primeira chamada" in rel["motivo"], rel)

print("— prefixo ESTÁVEL passa a ser marcado")
cp.esquece()
for _ in range(2):
    saida, rel = cp.prepara(msgs(), "anthropic/claude-sonnet-4")
checa("na segunda, marca", rel["marcou"] is True, rel)
checa("e diz que é idêntico", "idêntico" in rel["motivo"], rel)
bloco = saida[0]["content"]
checa("virou lista de blocos", isinstance(bloco, list), bloco)
checa("com cache_control efêmero",
      bloco[0].get("cache_control") == {"type": "ephemeral"}, bloco[0])
checa("preservando o texto", bloco[0]["text"] == GRANDE)
checa("e sem tocar no resto", saida[1] == {"role": "user", "content": "oi"}, saida[1])

print("— prefixo INSTÁVEL nunca é marcado (a armadilha cara)")
cp.esquece()
for i in range(5):
    # Um relógio no bloco de sistema: parece constante e não é.
    _, rel = cp.prepara(msgs(GRANDE + f"\nagora são {i}:00"), "anthropic/claude-sonnet-4")
checa("não marca prefixo que muda", rel["marcou"] is False, rel)
checa("e diz quantas vezes mudou", "mudou" in rel["motivo"], rel)
checa("explicando que sairia mais caro", "custaria mais" in rel["motivo"], rel)

print("— prefixo curto demais não vale a marca")
cp.esquece()
for _ in range(3):
    _, rel = cp.prepara(msgs("seja breve"), "anthropic/claude-sonnet-4")
checa("abaixo do mínimo não marca", rel["marcou"] is False, rel)
checa("e diz o mínimo", str(cp.MIN_TOKENS) in rel["motivo"], rel)

print("— provedor que cacheia sozinho não recebe marca")
cp.esquece()
for _ in range(3):
    saida, rel = cp.prepara(msgs(), "openai/gpt-4.1-mini")
checa("não marca", rel["marcou"] is False, rel)
checa("e diz por quê", "sozinho" in rel["motivo"], rel)
checa("mensagens intactas", saida[0]["content"] == GRANDE, "não pode mexer à toa")

print("— provedor desconhecido: não mexer é o seguro")
cp.esquece()
for _ in range(3):
    saida, rel = cp.prepara(msgs(), "fabricante-novo/modelo-x")
checa("não marca", rel["marcou"] is False, rel)
checa("mensagens intactas", saida[0]["content"] == GRANDE,
      "cache_control num provedor que não entende pode virar erro de validação")

print("— sem bloco de sistema não há o que cachear")
cp.esquece()
_, rel = cp.prepara([{"role": "user", "content": GRANDE}], "anthropic/claude-sonnet-4")
checa("não marca", rel["marcou"] is False, rel)
checa("e diz por quê", "sistema" in rel["motivo"], rel)

print("— marca UMA vez, no fim do prefixo")
cp.esquece()
tres = [{"role": "system", "content": GRANDE},
        {"role": "system", "content": "regra extra"},
        {"role": "user", "content": "oi"}]
for _ in range(2):
    saida, rel = cp.prepara(tres, "anthropic/claude-sonnet-4")
checa("marcou", rel["marcou"] is True, rel)
marcadas = [m for m in saida
            if isinstance(m.get("content"), list)
            and any(b.get("cache_control") for b in m["content"])]
checa("só um ponto de quebra", len(marcadas) == 1, len(marcadas))
checa("e é o último do prefixo", marcadas[0]["content"][0]["text"] == "regra extra",
      "cache_control significa 'cacheie até aqui'; marcar cada um gastaria os "
      "4 pontos de quebra sem cachear nada a mais")

print("— o prefixo para no primeiro não-sistema")
cp.esquece()
misto = [{"role": "system", "content": GRANDE},
         {"role": "user", "content": "oi"},
         {"role": "system", "content": "isto NÃO é prefixo"}]
for _ in range(2):
    saida, rel = cp.prepara(misto, "anthropic/claude-sonnet-4")
checa("o sistema tardio não entra no prefixo",
      saida[2]["content"] == "isto NÃO é prefixo", saida[2])

print("— forçar contorna a checagem, nos dois sentidos")
cp.esquece()
_, rel = cp.prepara(msgs(), "anthropic/claude-sonnet-4", forcar=True)
checa("forcar=True marca na primeira", rel["marcou"] is True, rel)
cp.esquece()
for _ in range(3):
    _, rel = cp.prepara(msgs(), "anthropic/claude-sonnet-4", forcar=False)
checa("forcar=False nunca marca", rel["marcou"] is False, rel)

print("— origens diferentes não se contaminam")
cp.esquece()
cp.prepara(msgs(), "anthropic/claude-sonnet-4", origem="chat")
_, rel = cp.prepara(msgs(), "anthropic/claude-sonnet-4", origem="agente")
checa("a segunda origem ainda está na primeira chamada", rel["marcou"] is False,
      "contar junto faria uma origem estável mascarar outra instável")

print("— entrada vazia não estoura")
saida, rel = cp.prepara([], "anthropic/claude-sonnet-4")
checa("devolve vazio", saida == [])
checa("com motivo", rel["motivo"] != "")

print()
if falhas:
    print(f"{len(falhas)} FALHA(S): " + ", ".join(falhas))
    sys.exit(1)
print("tudo passou")
