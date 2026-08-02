"""O arnês de avaliação — testado, porque uma régua sem aferição mede errado
com confiança.

O QUE ESTE TESTE PROTEGE

A propriedade que dá valor ao arnês inteiro: **ele consegue reprovar**. Um
detector de regressão que só sabe ficar verde é pior que nenhum, porque produz
a certeza de que nada quebrou.

Por isso os casos aqui atacam os jeitos de o arnês virar verde por acidente:
critério desconhecido virando aprovação, caso sem critério inflando o placar,
indefinido se passando por sucesso, e melhoria compensando regressão.
"""
import json
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from avaliacao import casos as mod_casos          # noqa: E402
from avaliacao import compara as mod_compara      # noqa: E402
from avaliacao import scorers                     # noqa: E402

falhas = []


def checa(nome, cond, detalhe=""):
    print(("  ok  " if cond else "FALHA") + "  " + nome + (f"  {detalhe}" if not cond and detalhe else ""))
    if not cond:
        falhas.append(nome)


print("— 'não sei' nunca vira aprovação")
n = scorers.aplica({"tipo": "inventado_por_typo", "valor": 1}, "qualquer coisa")
checa("critério desconhecido é indefinido, não verde", n.passou is None, n)
checa("e diz qual era", "inventado_por_typo" in n.detalhe, n)

checa("veredito com indefinido não passa",
      scorers.veredito([scorers.Nota(True), scorers.Nota(None)]) is None)
checa("uma falha ganha do indefinido",
      scorers.veredito([scorers.Nota(None), scorers.Nota(False)]) is False,
      "saber que quebrou é mais útil que saber que não deu pra julgar o resto")
checa("sem nota nenhuma é indefinido", scorers.veredito([]) is None)
checa("todas passando passa",
      scorers.veredito([scorers.Nota(True), scorers.Nota(True)]) is True)

print("— juiz por LLM ausente é indefinido, não aprovação")
n = scorers.aplica({"tipo": "juiz", "valor": "a resposta é educada?"}, "oi")
checa("sem julgador não aprova", n.passou is None, n)
checa("e explica por quê", "sem juiz" in n.detalhe, n)

print("— comparação por conteúdo, não por digitação")
checa("acento não reprova", scorers.contem("Foi em São Paulo", "sao paulo").passou is True)
checa("caixa não reprova", scorers.contem("PARIS", "paris").passou is True)
checa("espaço extra não reprova", scorers.contem("a  b", "a b").passou is True)

print("— lista de termos é conjunção (passar metade não é passar)")
r = scorers.contem("só o primeiro apareceu", ["primeiro", "segundo"])
checa("faltando um reprova", r.passou is False, r)
checa("e diz qual faltou", "segundo" in r.detalhe, r)

print("— resposta vazia não passa em 'nao_contem'")
checa("vazio reprova em nao_vazio", scorers.nao_vazio("").passou is False)
checa("só espaço também", scorers.nao_vazio("   \n ").passou is False)
checa("mas nao_contem sozinho aprovaria",
      scorers.nao_contem("", "proibido").passou is True,
      "é por isso que nao_vazio existe e os casos o usam junto")

print("— o julgador da fala pega o que a voz soletraria")
for texto, oque in [("Isso é **muito** importante", "negrito"),
                    ("## Título", "cerquilha"),
                    ("use `git status`", "crase"),
                    ("veja [aqui](https://x.com)", "link"),
                    ("Pronto! 🚀", "emoji"),
                    ("| a | b |", "tabela"),
                    ("- item", "marcador")]:
    checa(f"pega {oque}", scorers.sem_marcacao(texto).passou is False, texto)
checa("texto limpo passa",
      scorers.sem_marcacao("Bom dia, Victor. Você tem duas reuniões.").passou is True)

print("— custo desconhecido não é custo zero")
n = scorers.aplica({"tipo": "ate_usd", "valor": 0.01}, "x", meta={})
checa("sem custo registrado é indefinido", n.passou is None, n)
n = scorers.aplica({"tipo": "ate_usd", "valor": 0.01}, "x", meta={"custo_usd": 0.0})
checa("custo zero é zero e passa", n.passou is True, n)

print("— regex quebrada culpa o caso, não o sistema")
n = scorers.aplica({"tipo": "regex", "valor": "([sem fechar"}, "qualquer")
checa("regex inválida é indefinido", n.passou is None, n)

# ---------------------------------------------------------------------------
print("— o carregador recusa caso que passaria sempre")


def _escreve(linhas):
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "t.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in linhas),
                               encoding="utf-8")
    return d


def _recusa(linhas, trecho, nome):
    try:
        mod_casos.carrega(_escreve(linhas))
        checa(nome, False, "carregou sem reclamar")
    except mod_casos.CasoInvalido as e:
        checa(nome, trecho in str(e), str(e))


bom = {"id": "a", "alvo": "roteamento", "entrada": "oi",
       "criterios": [{"tipo": "engine", "valor": "ollama"}]}

_recusa([{**bom, "criterios": []}], "sem critério", "caso sem critério é recusado")
_recusa([bom, {**bom, "id": "a"}], "repetido", "id repetido é recusado")
_recusa([{**bom, "alvo": "inventado"}], "desconhecido", "alvo desconhecido é recusado")
_recusa([{**bom, "entrada": ""}], "entrada", "entrada vazia é recusada")
_recusa([{**bom, "criterios": [{"valor": 1}]}], "sem 'tipo'", "critério sem tipo é recusado")

carregados = mod_casos.carrega(_escreve([bom]))
checa("caso válido carrega", len(carregados) == 1 and carregados[0].id == "a")
checa("roteamento não custa", carregados[0].custa is False)

print("— os casos de verdade do projeto carregam")
reais = mod_casos.carrega()
checa("há casos", len(reais) >= 20, len(reais))
checa("todo caso tem etiqueta", all(c.etiquetas for c in reais),
      [c.id for c in reais if not c.etiquetas])
alvos = {c.alvo for c in reais}
checa("os três alvos estão cobertos", alvos == {"roteamento", "fala", "resposta"}, alvos)

# ---------------------------------------------------------------------------
print("— a comparação detecta o evento que importa")


def _exec(pares, custo=0.0):
    res = [{"id": i, "alvo": "roteamento", "passou": v,
            "notas": [{"criterio": "engine", "passou": v, "detalhe": "d"}]}
           for i, v in pares]
    return {"quando": "x", "git": "g", "engine": "ollama", "modelo": "",
            "resultados": res,
            "resumo": {"total": len(res), "passaram": sum(1 for _, v in pares if v is True),
                       "falharam": sum(1 for _, v in pares if v is False),
                       "indefinidos": sum(1 for _, v in pares if v is None),
                       "custo_usd": custo, "ms": 1}}


d = mod_compara.compara(_exec([("a", True)]), _exec([("a", False)]))
checa("passou -> falhou é regressão", [r["id"] for r in d["regressoes"]] == ["a"], d)

d = mod_compara.compara(_exec([("a", True)]), _exec([("a", None)]))
checa("passou -> indefinido também é regressão",
      [r["id"] for r in d["regressoes"]] == ["a"],
      "virar indefinido esconde a quebra atrás de uma palavra confortável")

d = mod_compara.compara(_exec([("a", False)]), _exec([("a", True)]))
checa("falhou -> passou é melhoria", [r["id"] for r in d["melhorias"]] == ["a"], d)
checa("e melhoria não é regressão", d["regressoes"] == [])

print("— melhoria NÃO compensa regressão")
d = mod_compara.compara(
    _exec([("a", True), ("b", False), ("c", False)]),
    _exec([("a", False), ("b", True), ("c", True)]))
checa("duas melhorias e uma quebra: ainda há regressão", len(d["regressoes"]) == 1, d)
checa("e as melhorias aparecem", len(d["melhorias"]) == 2, d)

print("— apagar o caso vermelho não deixa verde em silêncio")
d = mod_compara.compara(_exec([("a", True), ("b", False)]), _exec([("a", True)]))
checa("caso sumido é reportado", d["sumiram"] == ["b"], d)
checa("e não conta como melhoria", d["melhorias"] == [], d)

d = mod_compara.compara(_exec([("a", True)]), _exec([("a", True), ("novo", True)]))
checa("caso novo é reportado", d["novos"] == ["novo"], d)

d = mod_compara.compara(_exec([("a", True)]), _exec([("a", True)]))
checa("sem mudança, nada é reportado",
      not any([d["regressoes"], d["melhorias"], d["novos"], d["sumiram"]]), d)

print("— falha de execução não vira reprovação do produto")
n = scorers.Nota(None, "RuntimeError: node não encontrado", criterio="execucao")
checa("erro de ambiente é indefinido", scorers.veredito([n]) is None,
      "'não consegui perguntar' e 'o sistema errou' pedem ações opostas")

print()
if falhas:
    print(f"{len(falhas)} FALHA(S): " + ", ".join(falhas))
    sys.exit(1)
print("tudo passou")
