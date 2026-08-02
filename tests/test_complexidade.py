"""Roteamento heurístico — decidir sem gastar chamada.

O `router_llm.py` classifica CHAMANDO um LLM. É grátis hoje, mas grátis não é de
graça: é latência antes de começar a pensar, é dependência de rede, e é uma cota
que pode acabar. Esta heurística decide offline em microssegundos e deixa o
classificador como desempate.

O QUE ESTE TESTE PROTEGE

A assimetria dos erros. Errar pra cima (nuvem sem precisar) custa meio centavo;
errar pra baixo (local numa pergunta difícil) custa qualidade e provavelmente uma
segunda tentativa — que custa mais que a economia. Então a regra é: na dúvida,
sobe. O teste trava isso.

E trava as duas entradas que nenhum roteador estudado tem: orçamento e
criticidade.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.complexidade import decide, pontua, LIMIAR_LOCAL, LIMIAR_NUVEM  # noqa: E402

falhas = []


def checa(nome, cond, detalhe=""):
    print(("  ok  " if cond else "FALHA") + "  " + nome + (f"  {detalhe}" if not cond and detalhe else ""))
    if not cond:
        falhas.append(nome)


print("— pergunta simples vai pro local")
for txt in ["oi", "bom dia", "obrigado", "que horas são?", "ok"]:
    d = decide(txt, tem_local=True)
    checa(f'"{txt}" -> local', d["engine"] == "ollama", d)

print("— pergunta difícil vai pra nuvem")
dificeis = [
    "Analise a arquitetura deste módulo e explique por que o acoplamento aumentou:\n"
    "```python\nclass A:\n    def f(self): pass\n```",
    "Compare as duas abordagens e justifique qual escala melhor, passo a passo",
]
for txt in dificeis:
    d = decide(txt, tem_local=True)
    checa("difícil -> nuvem", d["engine"] == "openrouter", d)

print("— código sobe a pontuação")
checa("bloco de código pontua", pontua("```python\nx=1\n```") >= 3,
      pontua("```python\nx=1\n```"))
checa("texto curto sem código não", pontua("qual a capital da França") <= LIMIAR_LOCAL,
      pontua("qual a capital da França"))

print("— ferramentas empurram pra nuvem")
# Escolher ferramenta errada gasta uma rodada inteira: o desconto do local evapora.
sem = pontua("liste meus arquivos", tem_ferramentas=False)
com = pontua("liste meus arquivos", tem_ferramentas=True)
checa("ferramenta aumenta a pontuação", com > sem, {"sem": sem, "com": com})

print("— CRITICIDADE vence tudo (o eixo que ninguém tem)")
# Pergunta trivial, orçamento zerado, e ainda assim vai pro modelo bom:
# economizar meio centavo e errar um comando destrutivo sai muito mais caro.
d = decide("apaga", tem_local=True, saldo_usd=0.0, critico=True)
checa("crítico ignora simplicidade e orçamento", d["engine"] == "openrouter", d)
checa("e diz por quê", "crític" in d["motivo"], d)

print("— ORÇAMENTO vira comportamento, não relatório")
d = decide("me explique detalhadamente a arquitetura e compare com a anterior",
           tem_local=True, saldo_usd=0.0)
checa("sem saldo, pergunta difícil ainda vai pro local", d["engine"] == "ollama", d)
checa("e diz que foi o orçamento", "orçamento" in d["motivo"], d)
# Responder com modelo fraco é melhor que não responder.
d2 = decide("qualquer coisa", tem_local=True, saldo_usd=5.0)
checa("com saldo, a regra normal volta", d2["motivo"] != "orçamento do mês esgotado", d2)

print("— sem local não há escolha")
d = decide("oi", tem_local=False)
checa("cai na nuvem", d["engine"] == "openrouter", d)
checa("e diz o motivo", "local" in d["motivo"], d)

print("— a alternância c/qu do português")
# "explicar" tem C, "explique" tem QU. Uma raiz `explic\w*` casa com
# "explicação" e NÃO com "explique" — que é a forma imperativa, a mais provável
# numa pergunta ao assistente. Custou uma investigação até os códigos de
# caractere mostrarem `e,x,p,l,i,q` onde eu esperava um `c`.
for verbo in ["explique", "explicação", "justifique", "justificar",
              "verifique", "verificar"]:
    checa(f'"{verbo}" conta como raciocínio',
          pontua(f"me {verbo} isso") > 0, pontua(f"me {verbo} isso"))

print("— na dúvida, SOBE (assimetria dos erros)")
achou_cinza = False
for txt in ["Compare as duas abordagens e justifique qual escala melhor, passo a passo",
            "explique este erro e analise o traceback"]:
    d = decide(txt, tem_local=True)
    if d["desempatar"]:
        achou_cinza = True
        checa("zona cinzenta sobe pra nuvem", d["engine"] == "openrouter", d)
        checa("e avisa que vale desempatar", d["desempatar"] is True, d)
checa("existe zona cinzenta", achou_cinza,
      "sem ela, a heurística finge certeza que não tem")

print("— os limiares fazem sentido")
checa("local < nuvem", LIMIAR_LOCAL < LIMIAR_NUVEM)
checa("há espaço pra dúvida", LIMIAR_NUVEM - LIMIAR_LOCAL >= 2,
      "sem folga, toda pergunta seria decidida com falsa convicção")

print("— texto vazio não quebra")
checa("vazio pontua zero", pontua("") == 0)
checa("None não estoura", pontua(None) == 0)

print()
if falhas:
    print(f"{len(falhas)} FALHA(S): " + ", ".join(falhas))
    sys.exit(1)
print("tudo passou")
