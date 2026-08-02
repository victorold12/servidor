"""Anti-laço do agente autônomo.

O teto de passos (`max_steps`) pega o laço óbvio. NÃO pega o caso comum: o
agente chama a mesma ferramenta com argumento levemente diferente, parecendo
progredir, e gasta o orçamento inteiro sem sair do lugar. Num projeto com R$
50/mês, um agente em laço queima a cota do mês numa madrugada.

A versão anterior contava FREQUÊNCIA numa janela de 4 — e por isso via só o
padrão mais simples. Alternância (A,B,A,B) tem cada assinatura aparecendo duas
vezes, então nunca disparava; e um ciclo de três não cabia na janela.

Este teste trava os três padrões e, principalmente, trava que trabalho legítimo
repetitivo NÃO seja interrompido — um falso positivo aqui mata tarefa boa.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.routers.autonomous import detecta_laco, LACO_AVISOS_ATE_PARAR  # noqa: E402

falhas = []


def checa(nome, cond, detalhe=""):
    print(("  ok  " if cond else "FALHA") + "  " + nome + (f"  {detalhe}" if not cond and detalhe else ""))
    if not cond:
        falhas.append(nome)


print("— nada de errado")
checa("lista vazia", detecta_laco([]) is None)
checa("uma chamada", detecta_laco(["a"]) is None)
checa("duas diferentes", detecta_laco(["a", "b"]) is None)
checa("progresso normal", detecta_laco(["a", "b", "c", "d", "e"]) is None,
      detecta_laco(["a", "b", "c", "d", "e"]))

print("— repetição direta (já era detectada)")
checa("mesma chamada 3x", detecta_laco(["a", "a", "a"]) is not None)
checa("e diz o motivo", "três vezes" in (detecta_laco(["x", "a", "a", "a"]) or ""),
      detecta_laco(["x", "a", "a", "a"]))
checa("2x seguidas ainda não é laço", detecta_laco(["a", "a"]) is None,
      "verificar duas vezes é comportamento legítimo")

print("— alternância A,B,A,B (o padrão que escapava)")
# Cada assinatura aparece só 2 vezes: a contagem por frequência nunca disparava.
# É o caso mais comum — o modelo "confere" o resultado rechamando a anterior.
r = detecta_laco(["a", "b", "a", "b"])
checa("A,B,A,B é laço", r is not None, r)
checa("e diz que é ciclo", "ciclo" in (r or ""), r)
checa("A,B,A sozinho ainda não é", detecta_laco(["a", "b", "a"]) is None)

print("— ciclo de três A,B,C,A,B,C")
r3 = detecta_laco(["a", "b", "c", "a", "b", "c"])
checa("A,B,C,A,B,C é laço", r3 is not None, r3)
checa("A,B,C,A,B ainda não fechou o ciclo",
      detecta_laco(["a", "b", "c", "a", "b"]) is None,
      detecta_laco(["a", "b", "c", "a", "b"]))

print("— trabalho legítimo NÃO pode ser interrompido")
# Processar 30 arquivos com a mesma ferramenta é repetição saudável: a
# ferramenta se repete, os ARGUMENTOS não. A assinatura inclui os argumentos
# justamente por isso.
lote = [f"fetch_url{{'url':'p{i}'}}" for i in range(12)]
checa("mesma ferramenta com alvos diferentes não é laço",
      detecta_laco(lote) is None, detecta_laco(lote))
# Voltar a uma chamada anterior depois de progredir também é legítimo.
checa("revisitar sem ciclo não é laço",
      detecta_laco(["a", "b", "c", "d", "a"]) is None,
      detecta_laco(["a", "b", "c", "d", "a"]))

print("— a escalada existe e é finita")
checa("avisa antes de parar", LACO_AVISOS_ATE_PARAR >= 2,
      f"avisar ao menos uma vez dá chance de o modelo mudar (é {LACO_AVISOS_ATE_PARAR})")
checa("mas para em algum momento", LACO_AVISOS_ATE_PARAR <= 3,
      "avisar sem nunca parar deixa o teto de passos ser queimado girando")

print()
if falhas:
    print(f"{len(falhas)} FALHA(S): " + ", ".join(falhas))
    sys.exit(1)
print("tudo passou")
