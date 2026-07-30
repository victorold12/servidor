"""RAG nos documentos do usuário: indexar, buscar, reindexar e apagar.

Sem pytest (`python3 tests/test_docs_rag.py`), igual aos outros.

Este ambiente não tem provedor de embeddings, então a busca aqui roda no modo
léxico. Isso NÃO invalida o teste — o que está sendo cobrado é a mecânica que
vale nos dois modos: o fatiamento, a sobreposição, a substituição ao reindexar,
a origem no resultado e a limpeza ao apagar. O que depende de vetor de verdade
(achar sinônimo) é justamente o que este ambiente não pode provar, e o teste
não finge que prova.

O que fica travado aqui:
  - texto curto vira um pedaço só; texto longo vira vários
  - os pedaços SE SOBREPÕEM (o defeito silencioso mais comum de RAG caseiro:
    sem sobreposição, a frase que cai na fronteira some das duas buscas)
  - o corte prefere fim de parágrafo a meio de frase
  - reindexar o mesmo nome SUBSTITUI, não duplica
  - documento que encolheu não deixa pedaço órfão buscável
  - o resultado da busca diz de qual documento veio
  - apagar tira o metadado E os pedaços
  - documento gigante é recusado com motivo, não truncado em silêncio
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["JARVIS_DB_PATH"] = os.path.join(
    tempfile.mkdtemp(prefix="vtz-docs-"), "teste.db")
os.environ.pop("RENDER", None)

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402
from app.routers.docs import MAX_CHARS, SOBREPOSICAO, fatiar  # noqa: E402

# init_db() roda no lifespan, e o lifespan só dispara com o TestClient usado
# como contexto. Chamar direto aqui deixa o teste linear em vez de aninhar o
# arquivo inteiro dentro de um `with`.
db.init_db()
cli = TestClient(app)
falhas = []


def checa(nome, cond, extra=""):
    print(("  ok  " if cond else "FALHA ") + nome + ("" if cond else f"  {extra!r}"))
    if not cond:
        falhas.append(nome)


print("— fatiamento")
checa("texto vazio não gera pedaço", fatiar("   ") == [])
curto = "Uma frase curta e só."
checa("texto curto vira um pedaço", fatiar(curto) == [curto], fatiar(curto))

# Parágrafos numerados: dá pra afirmar QUAL conteúdo caiu em qual pedaço.
longo = "\n\n".join(f"Paragrafo numero {i} com bastante texto para encher o pedaco. "
                    * 6 for i in range(40))
pedacos = fatiar(longo)
checa("texto longo vira vários pedaços", len(pedacos) > 3, len(pedacos))
checa("nenhum pedaço vazio", all(p.strip() for p in pedacos))

# A sobreposição de verdade: o fim de um pedaço tem que reaparecer no começo do
# seguinte. Comparar o texto, não o tamanho — tamanho passa por acidente.
sobrepoe = 0
for a, b in zip(pedacos, pedacos[1:]):
    cauda = a[-120:]
    if cauda and cauda in b[:SOBREPOSICAO + 200]:
        sobrepoe += 1
checa("os pedaços se sobrepõem", sobrepoe >= len(pedacos) - 2,
      f"{sobrepoe} de {len(pedacos) - 1} fronteiras")

cortes_limpos = sum(1 for p in pedacos[:-1] if p.rstrip().endswith((".", "!", "?")))
checa("o corte prefere fim de frase", cortes_limpos >= len(pedacos) // 2,
      f"{cortes_limpos} de {len(pedacos) - 1}")

print("— indexar")
SEGREDO = "O codigo do portao da casa e 4471."
r = cli.post("/api/docs", json={"name": "anotacoes.txt",
                                "text": f"Coisas da casa.\n\n{SEGREDO}\n\nFim."})
checa("indexou", r.status_code == 200, r.text[:160])
d = r.json()
checa("devolveu quantos pedaços", d["chunks"] >= 1, d)
checa("diz o modo em que indexou", d["mode"] in ("semantic", "lexical"), d.get("mode"))
checa("sem provedor, avisa que é por termos",
      d["mode"] == "lexical" and "EMBEDDINGS_BASE" in (d.get("note") or ""), d.get("note"))
doc_id = d["doc_id"]

r = cli.get("/api/docs")
checa("aparece na lista", any(x["name"] == "anotacoes.txt" for x in r.json()["documents"]),
      r.json())

print("— buscar")
r = cli.get("/api/memory/search", params={"q": "codigo do portao"})
res = r.json()["results"]
checa("achou o trecho", any(SEGREDO in x["text"] for x in res),
      [x["text"][:60] for x in res])
achado = next((x for x in res if SEGREDO in x["text"]), None)
checa("o resultado é da espécie doc", achado and achado["kind"] == "doc", achado)
checa("e diz de qual documento veio", achado and achado.get("source") == "anotacoes.txt",
      achado.get("source") if achado else None)

print("— reindexar o mesmo nome substitui, não duplica")
r = cli.post("/api/docs", json={"name": "anotacoes.txt",
                                "text": "Agora o portao mudou: o codigo e 9902."})
checa("reindexou", r.status_code == 200, r.text[:120])
checa("mesmo doc_id", r.json()["doc_id"] == doc_id, r.json()["doc_id"])
lista = cli.get("/api/docs").json()["documents"]
checa("continua sendo UM documento", sum(1 for x in lista if x["name"] == "anotacoes.txt") == 1,
      lista)

res = cli.get("/api/memory/search", params={"q": "codigo do portao"}).json()["results"]
checa("o código velho não é mais encontrável", not any("4471" in x["text"] for x in res),
      [x["text"][:60] for x in res])
checa("o novo é", any("9902" in x["text"] for x in res), [x["text"][:60] for x in res])

print("— reindex geral não perde os documentos")
r = cli.post("/api/memory/reindex")
checa("reindex responde", r.status_code == 200, r.text[:120])
checa("conta os pedaços de documento", r.json().get("doc_chunks", 0) >= 1, r.json())
res = cli.get("/api/memory/search", params={"q": "codigo do portao"}).json()["results"]
checa("ainda encontra depois do reindex", any("9902" in x["text"] for x in res),
      [x["text"][:60] for x in res])

print("— apagar leva os pedaços junto")
r = cli.delete(f"/api/docs/{doc_id}")
checa("apagou", r.status_code == 200, r.text[:120])
checa("sumiu da lista", not cli.get("/api/docs").json()["documents"])
res = cli.get("/api/memory/search", params={"q": "codigo do portao"}).json()["results"]
checa("e o texto não é mais encontrável", not any("9902" in x["text"] for x in res),
      [x["text"][:60] for x in res])
checa("apagar de novo dá 404", cli.delete(f"/api/docs/{doc_id}").status_code == 404)

print("— recusas honestas")
r = cli.post("/api/docs", json={"name": "gigante.txt", "text": "a" * (MAX_CHARS + 1)})
checa("documento gigante é recusado", r.status_code == 413, r.status_code)
checa("e o erro diz o teto", str(MAX_CHARS) in r.text, r.text[:160])
checa("documento vazio é recusado",
      cli.post("/api/docs", json={"name": "x.txt", "text": "   "}).status_code in (400, 422))

print("\n" + (f"{len(falhas)} FALHA(S): {', '.join(falhas)}" if falhas else "tudo passou"))
sys.exit(1 if falhas else 0)
