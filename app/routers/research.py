"""/api/deep-research — pesquisa profunda no servidor, com progresso via SSE.

Faz o loop completo no backend (mais robusto que no navegador): quebra o tema em
sub-perguntas, busca cada uma na web, e sintetiza um relatório com fontes. Vai
transmitindo eventos para o site mostrar o progresso ao vivo.
"""
import json
import re

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..openrouter import chat, content_of, resolve_key
from ..services import web_search

router = APIRouter()


class ResearchIn(BaseModel):
    topic: str
    model: str | None = None
    max_subquestions: int = 4


def _parse_subquestions(raw: str, topic: str, limit: int) -> list[str]:
    match = re.search(r"\[[\s\S]*\]", raw)
    if match:
        try:
            arr = json.loads(match.group(0))
            subs = [s.strip() for s in arr if isinstance(s, str) and len(s.strip()) > 4]
            if subs:
                return subs[:limit]
        except json.JSONDecodeError:
            pass
    lines = [re.sub(r"^[-*\d.\s]+", "", ln).strip() for ln in raw.splitlines()]
    subs = [ln for ln in lines if len(ln) > 4]
    return subs[:limit] or [topic]


@router.post("/deep-research")
async def deep_research(
    body: ResearchIn,
    x_or_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    key = resolve_key(x_or_key or authorization)

    async def gen():
        def sse(event: str, **data) -> str:
            return "data: " + json.dumps({"event": event, **data}, ensure_ascii=False) + "\n\n"

        try:
            yield sse("status", message="Quebrando o tema em sub-perguntas…")
            planning = await chat(
                [{"role": "user", "content":
                  f"Quebre o tema abaixo em {body.max_subquestions} sub-perguntas de "
                  f"pesquisa objetivas e complementares. Responda SÓ com um array JSON "
                  f"de strings.\n\nTema: {body.topic}"}],
                key=key, model=body.model,
            )
            subs = _parse_subquestions(content_of(planning), body.topic, body.max_subquestions)
            yield sse("subquestions", items=subs)

            findings = []
            for question in subs:
                yield sse("status", message=f"Pesquisando: {question}")
                hits = await web_search(question, 5)
                context = "\n".join(
                    f"- {h['title']} ({h['url']}): {h['snippet']}" for h in hits
                ) or "(sem resultados)"
                answer = content_of(await chat(
                    [{"role": "user", "content":
                      f"Pergunta: {question}\n\nResultados de busca:\n{context}\n\n"
                      f"Responda com fatos concretos e cite as fontes (com links)."}],
                    key=key, model=body.model,
                ))
                findings.append(f"### {question}\n{answer}")
                yield sse("finding", question=question, answer=answer,
                          sources=[h["url"] for h in hits])

            yield sse("status", message="Sintetizando o relatório final…")
            report = content_of(await chat(
                [{"role": "user", "content":
                  f"Com base SÓ nas descobertas abaixo, escreva um relatório final sobre "
                  f"\"{body.topic}\". Use \"## seções\", **negrito**, listas e uma seção "
                  f"final \"## Conclusão\". Cite as fontes (links). Seja honesto sobre o "
                  f"que ficou incerto.\n\n" + "\n\n".join(findings)}],
                key=key, model=body.model,
            ))
            yield sse("report", markdown=report)
            yield sse("done")
        except Exception as exc:  # noqa: BLE001
            yield sse("error", message=str(exc))

    return StreamingResponse(gen(), media_type="text/event-stream")
