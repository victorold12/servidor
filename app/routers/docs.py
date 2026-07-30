"""/api/docs — os documentos DO USUÁRIO, buscáveis por significado (RAG).

O QUE ISTO RESOLVE. Até aqui, "conhecimento do projeto" era um campo de texto
colado inteiro no prompt a cada mensagem (painel, 16-photo-resize-misc.js:150).
Funciona pra meia página de instrução e falha em tudo mais: um PDF de 80 páginas
não cabe na janela, e mesmo cabendo você pagaria por ele em TODA mensagem, para
usar três parágrafos.

Aqui o documento é quebrado em pedaços, cada pedaço vira um vetor, e só os
pedaços que interessam à pergunta vão pro modelo. Paga-se pelo que se usa.

ONDE O TEXTO MORA. Os pedaços vão pra `memory_vectors` com kind='doc' — a mesma
tabela da memória em grafo e do resumo diário. Não é economia de tabela: é que
/api/memory/search varre memory_vectors SEM filtrar espécie, então documento
entra na mesma busca que o resto sem uma segunda consulta e sem código novo do
lado de quem pergunta. Esta tabela `documents` guarda só o metadado, porque sem
ele não dá pra listar nem apagar um documento inteiro.

O QUE ESTE MÓDULO NÃO FAZ, DE PROPÓSITO: não lê PDF, DOCX nem HTML. Recebe
TEXTO. O painel já extrai texto de anexo no navegador pra montar as mensagens —
reaproveitar isso deixa o backend sem dependência nova (nada de pypdf) e sem
precisar de um megabyte de binário subindo por HTTP. Quem chama manda o texto.
"""
import hashlib
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db, embeddings
from .memory import _USER, _indexa

router = APIRouter()

# Teto por documento. 400 mil caracteres é um livro; acima disso a indexação
# começa a demorar o suficiente pra estourar o timeout de um plano grátis, e o
# erro honesto ("grande demais") é melhor que uma requisição que morre no meio
# deixando metade dos pedaços gravados.
MAX_CHARS = 400_000

# ~3200 caracteres ≈ 800 tokens em português. Pedaço grande demais dilui: o
# vetor vira a média de assuntos diferentes e não casa com pergunta nenhuma.
# Pequeno demais perde o contexto que dá sentido à frase.
TAMANHO_PEDACO = 3200

# 15% de sobreposição. Sem ela, uma frase que cai exatamente na fronteira fica
# partida entre dois pedaços e some das duas buscas — cada metade sozinha não
# casa com a pergunta. É o defeito mais comum de RAG caseiro, e é silencioso:
# a resposta simplesmente "não achou", sem erro nenhum.
SOBREPOSICAO = 480


def fatiar(texto: str) -> list[str]:
    """Quebra o texto em pedaços com sobreposição, preferindo cortar em
    parágrafo.

    Cortar no meio de uma frase é pior que um pedaço irregular: o começo do
    pedaço seguinte fica sem sujeito, e o vetor dele passa a representar uma
    frase que ninguém escreveu. Por isso a procura por quebra de parágrafo (e
    depois por fim de frase) dentro dos últimos 30% do pedaço — perto o
    bastante do tamanho alvo pra não deformar, longe o bastante pra achar uma.
    """
    texto = (texto or "").strip()
    if not texto:
        return []

    pedacos: list[str] = []
    inicio = 0
    limite = len(texto)
    while inicio < limite:
        fim = min(inicio + TAMANHO_PEDACO, limite)
        if fim < limite:
            janela_min = inicio + int(TAMANHO_PEDACO * 0.7)
            corte = texto.rfind("\n\n", janela_min, fim)
            if corte == -1:
                corte = texto.rfind(". ", janela_min, fim)
                if corte != -1:
                    corte += 1          # o ponto fica com a frase que o gerou
            if corte > inicio:
                fim = corte
        pedaco = texto[inicio:fim].strip()
        if pedaco:
            pedacos.append(pedaco)
        if fim >= limite:
            break
        # o próximo começa ANTES do fim deste: é aqui que a sobreposição existe
        inicio = max(fim - SOBREPOSICAO, inicio + 1)
    return pedacos


def _id_do_nome(nome: str) -> str:
    """Id estável a partir do nome. Reindexar o mesmo arquivo SUBSTITUI o
    anterior em vez de criar um segundo — senão a busca passaria a devolver o
    mesmo trecho duas vezes, uma da versão velha e outra da nova, e não haveria
    como saber qual é qual."""
    return hashlib.sha256(nome.strip().lower().encode("utf-8")).hexdigest()[:16]


class IndexIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)


@router.post("/docs")
async def index_doc(body: IndexIn):
    """Indexa (ou reindexa) um documento."""
    if len(body.text) > MAX_CHARS:
        raise HTTPException(
            status_code=413,
            detail=(f"Documento com {len(body.text)} caracteres; o teto é {MAX_CHARS}. "
                    "Divida em partes menores e indexe uma de cada vez."))

    pedacos = fatiar(body.text)
    if not pedacos:
        raise HTTPException(status_code=400, detail="Documento vazio depois de limpar espaços.")

    doc_id = _id_do_nome(body.name)

    # Apaga os pedaços da versão anterior ANTES de gravar a nova. Se o documento
    # encolheu, os pedaços do fim da versão velha ficariam órfãos na busca —
    # texto que não está mais no arquivo, aparecendo como se estivesse.
    with db.get_conn() as conn:
        conn.execute(
            "DELETE FROM memory_vectors WHERE user_id = ? AND kind = 'doc' AND ref LIKE ?",
            (_USER, f"{doc_id}#%"))

    # O nome vai junto no texto indexado: a pergunta muitas vezes cita o
    # documento ("o que o contrato diz sobre...") e sem o nome no vetor esse
    # sinal se perde.
    await _indexa("doc", [(f"{doc_id}#{n}", f"[{body.name}]\n{p}")
                          for n, p in enumerate(pedacos)])

    agora = time.time()
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO documents (user_id, doc_id, name, chars, chunks, indexed_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(user_id, doc_id) DO UPDATE SET "
            "name = excluded.name, chars = excluded.chars, chunks = excluded.chunks, "
            "indexed_at = excluded.indexed_at",
            (_USER, doc_id, body.name, len(body.text), len(pedacos), agora))

    return {
        "ok": True,
        "doc_id": doc_id,
        "name": body.name,
        "chunks": len(pedacos),
        "chars": len(body.text),
        # Diz o que REALMENTE aconteceu. Sem provedor de embeddings o pedaço é
        # guardado com marcador léxico e a busca acha por palavra, não por
        # significado — chamar isso de semântico seria mentir sobre a
        # capacidade, e o usuário só descobriria ao não achar o que procurava.
        "mode": "semantic" if embeddings.configured() else "lexical",
        "note": None if embeddings.configured() else (
            "indexado por termos: configure EMBEDDINGS_BASE e EMBEDDINGS_MODEL "
            "e rode /api/memory/reindex pra busca por significado"),
    }


@router.get("/docs")
def list_docs():
    with db.get_conn() as conn:
        linhas = conn.execute(
            "SELECT doc_id, name, chars, chunks, indexed_at FROM documents "
            "WHERE user_id = ? ORDER BY indexed_at DESC", (_USER,)).fetchall()
    return {"documents": [dict(r) for r in linhas],
            "mode": "semantic" if embeddings.configured() else "lexical"}


@router.delete("/docs/{doc_id}")
def delete_doc(doc_id: str):
    """Apaga o documento e todos os pedaços dele.

    Os dois DELETE ficam no MESMO `with`: se o segundo falhasse depois de o
    primeiro ter commitado, sobrariam pedaços buscáveis de um documento que a
    lista diz não existir mais — e não haveria tela nenhuma pra removê-los.
    """
    with db.get_conn() as conn:
        achou = conn.execute(
            "SELECT 1 FROM documents WHERE user_id = ? AND doc_id = ?",
            (_USER, doc_id)).fetchone()
        if not achou:
            raise HTTPException(status_code=404, detail="Documento não encontrado.")
        conn.execute(
            "DELETE FROM memory_vectors WHERE user_id = ? AND kind = 'doc' AND ref LIKE ?",
            (_USER, f"{doc_id}#%"))
        conn.execute("DELETE FROM documents WHERE user_id = ? AND doc_id = ?",
                     (_USER, doc_id))
    return {"ok": True, "doc_id": doc_id}
