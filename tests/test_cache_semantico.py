"""Cache de resposta.

O QUE ESTE TESTE PROTEGE

Este é o único módulo do bloco de custo que pode fazer o sistema MENTIR. Os
outros dois erram gastando mais; este erra devolvendo a resposta de ontem pra
pergunta de hoje.

Então a maior parte dos casos aqui verifica o que ele SE RECUSA a fazer:
não cachear pergunta que depende do relógio, do estado pessoal, ou que ia
disparar uma ação. O acerto é a parte fácil; a recusa é o produto.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.cache_semantico import (  # noqa: E402
    Cache, cacheavel, digital_contexto, semelhanca,
)

falhas = []


def checa(nome, cond, detalhe=""):
    print(("  ok  " if cond else "FALHA") + "  " + nome + (f"  {detalhe}" if not cond and detalhe else ""))
    if not cond:
        falhas.append(nome)


print("— O QUE NUNCA ENTRA: pergunta que depende do relógio")
for p in ["que horas são no Japão",
          "o que eu tenho hoje na agenda",
          "qual a cotação do dólar agora",
          "quais foram as últimas notícias",
          "o que aconteceu ontem no mercado"]:
    pode, motivo = cacheavel(p)
    checa(f'recusa "{p[:32]}"', pode is False, motivo)

print("— O QUE NUNCA ENTRA: pergunta sobre estado pessoal")
for p in ["quantos arquivos tem na minha pasta de downloads",
          "quanto eu gastei este mês com a API",
          "qual o saldo da minha conta",
          "tem algo na minha caixa de entrada"]:
    pode, motivo = cacheavel(p)
    checa(f'recusa "{p[:32]}"', pode is False, motivo)

print("— O QUE NUNCA ENTRA: pergunta que ia agir")
pode, motivo = cacheavel("apague os arquivos temporários da pasta", tem_ferramentas=True)
checa("recusa quando há ferramentas", pode is False, motivo)
checa("e diz que o cache não executa", "não executa" in motivo, motivo)

print("— o que PODE entrar")
for p in ["qual é a capital da França",
          "explique o que é uma árvore binária de busca",
          "quem escreveu Grande Sertão Veredas"]:
    pode, motivo = cacheavel(p)
    checa(f'aceita "{p[:32]}"', pode is True, motivo)

print("— acerto por pergunta idêntica (o caso que mais vale)")
c = Cache()
c.guarda("Qual é a capital da França?", "Paris.")
r, motivo = c.consulta("qual e a capital da frança?")
checa("acha com outra caixa e acento", r == "Paris.", motivo)
checa("e diz que foi idêntica", "idêntica" in motivo, motivo)
r, _ = c.consulta("   Qual   é a  capital da França  ")
checa("espaçamento não atrapalha", r == "Paris.")

print("— pergunta DIFERENTE não é servida do cache")
c = Cache()
c.guarda("qual é a capital da França", "Paris.")
r, motivo = c.consulta("qual é a capital da Itália")
checa("capital de outro país não acerta", r is None, f"devolveu {r!r} — {motivo}")
r, _ = c.consulta("qual é a moeda da França")
checa("outra pergunta sobre o mesmo país também não", r is None, r)

print("— contexto diferente é outra pergunta")
c = Cache()
ctx_a = digital_contexto([{"role": "system", "content": "seja formal"}], "modelo-x")
ctx_b = digital_contexto([{"role": "system", "content": "seja informal"}], "modelo-x")
checa("digitais diferem", ctx_a != ctx_b)
c.guarda("explique recursão em uma frase", "Formal.", contexto=ctx_a)
r, _ = c.consulta("explique recursão em uma frase", contexto=ctx_b)
checa("não vaza entre contextos", r is None, r)
r, _ = c.consulta("explique recursão em uma frase", contexto=ctx_a)
checa("mas acha no contexto certo", r == "Formal.", r)

print("— o modelo faz parte da identidade do contexto")
ctx_m1 = digital_contexto([{"role": "system", "content": "s"}], "anthropic/claude")
ctx_m2 = digital_contexto([{"role": "system", "content": "s"}], "openai/gpt")
checa("modelos diferentes, digitais diferentes", ctx_m1 != ctx_m2)

print("— a pergunta do usuário NÃO entra na digital do contexto")
# Senão cada pergunta teria contexto próprio e o cache nunca acertaria.
d1 = digital_contexto([{"role": "system", "content": "s"}, {"role": "user", "content": "a"}], "m")
d2 = digital_contexto([{"role": "system", "content": "s"}, {"role": "user", "content": "b"}], "m")
checa("mesma conversa, digital igual", d1 == d2)

print("— expira pelo tempo")
c = Cache(ttl_s=0.3)
c.guarda("explique o teorema de Pitágoras", "a²+b²=c².")
checa("acha logo depois", c.consulta("explique o teorema de Pitágoras")[0] is not None)
time.sleep(0.4)
checa("não acha depois do prazo",
      c.consulta("explique o teorema de Pitágoras")[0] is None)

print("— resposta vazia não é guardada")
c = Cache()
checa("string vazia recusada", c.guarda("qual a capital da França", "") is False)
checa("só espaço recusado", c.guarda("qual a capital da França", "   ") is False)

print("— não guarda o que não pode servir")
c = Cache()
checa("pergunta com relógio não é guardada",
      c.guarda("que horas são agora", "10h") is False,
      "guardar o que nunca será servido só gastaria memória")

print("— o limiar é alto de propósito")
c = Cache(limiar=0.92)
c.guarda("explique o que é uma árvore binária de busca", "É uma estrutura...")
r, _ = c.consulta("explique o que é uma árvore binária")
checa("parafrase próxima ainda não acerta", r is None,
      "o ganho de cachear parafrase é pequeno e o risco é grande")

print("— semelhança")
checa("iguais dão 1.0", semelhanca("capital da França", "capital da França") == 1.0)
checa("nada em comum dá 0", semelhanca("capital da França", "receita de bolo") == 0.0)
checa("palavras vazias não inflam",
      semelhanca("qual é a capital da França", "capital França") > 0.9,
      "sem remover 'qual/é/a/da', duas formas da mesma pergunta pareceriam diferentes")

print("— o placar separa recusa de erro")
c = Cache()
c.guarda("qual é a capital da França", "Paris.")
c.consulta("qual é a capital da França")          # acerto
c.consulta("qual é a capital da Itália")          # erro
c.consulta("que horas são agora")                 # recusa
s = c.resumo()
checa("um acerto", s["acertos"] == 1, s)
checa("um erro", s["erros"] == 1, s)
checa("uma recusa", s["recusas"] == 1, s)
checa("a taxa ignora recusas", s["taxa"] == 0.5, s)
c2 = Cache()
checa("sem consulta, taxa é None e não 0",
      c2.resumo()["taxa"] is None,
      "zero diria 'nunca acerta'; None diz 'ninguém perguntou'")

print("— não cresce sem limite")
c = Cache(tamanho_max=10)
for i in range(50):
    c.guarda(f"explique detalhadamente o conceito numero {i} da lista", f"resposta {i}")
checa("respeita o teto", c.resumo()["entradas"] <= 10, c.resumo())
checa("e mantém o mais recente",
      c.consulta("explique detalhadamente o conceito numero 49 da lista")[0] == "resposta 49")

# ---------------------------------------------------------------------------
# LIGAÇÃO COM O PRODUTO
import pathlib  # noqa: E402

_raiz = pathlib.Path(__file__).resolve().parent.parent
_or = (_raiz / "app" / "openrouter.py").read_text(encoding="utf-8")
print("— o chat de fato consulta e alimenta o cache")
checa("importa os dois caches", "cache_prompt, cache_semantico" in _or)
checa("consulta antes da rede", "cache_semantico.cache.consulta(" in _or)
checa("guarda depois do acerto", "cache_semantico.cache.guarda(" in _or)
checa("marca o prefixo", "cache_prompt.prepara(" in _or)
# Contar tokens de uma chamada que não aconteceu inflaria o gasto medido.
checa("resposta de cache não conta tokens", '"prompt_tokens": 0' in _or)

_aval = (_raiz / "avaliacao" / "executa.py").read_text(encoding="utf-8")
print("— o arnês NÃO usa cache (senão mediria a si mesmo)")
checa("avaliação desliga o cache", "cache=False" in _aval,
      "com cache, a segunda execução acertaria tudo em 0ms e esconderia regressão")

print()
if falhas:
    print(f"{len(falhas)} FALHA(S): " + ", ".join(falhas))
    sys.exit(1)
print("tudo passou")
