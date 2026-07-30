"""/api/orchestrate — orquestrador "planeja → paraleliza → sintetiza".

Padrão absorvido do rezaulhreza/jarvis (Seção 13.1): o LLM quebra uma tarefa
complexa em subtarefas com DEPENDÊNCIAS declaradas (um DAG), o executor roda em
PARALELO todas as subtarefas cujas dependências já terminaram, e no fim
sintetiza tudo. Diferente do /api/deep-research (sub-perguntas sequenciais) e do
/api/autonomous (loop sequencial de um agente) — aqui o ganho é a paralelização
de partes independentes.

O núcleo (planejamento do DAG, execução por níveis, síntese) é separado da
camada HTTP e recebe a função de LLM injetada — dá pra testar a concorrência e a
ordem de dependência sem tocar na rede nem no OpenRouter (ver tests/
test_orchestrate.py).
"""
import asyncio
import json
import re

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..openrouter import chat, content_of, resolve_key
from ..services import web_search

router = APIRouter()

_MAX_SUBTASKS = 8


class OrchestrateIn(BaseModel):
    task: str
    model: str | None = None
    max_subtasks: int = 5
    web: bool = True  # subtarefas podem buscar na web antes de responder


# ---------------- Núcleo testável (sem HTTP, LLM injetável) ----------------

def parse_plan(raw: str, limit: int) -> list[dict]:
    """Extrai o DAG do texto do LLM. Cada subtarefa: {id, goal, deps:[ids]}.
    Saneia: ids únicos, deps que apontam só pra ids existentes, sem auto-loop.
    Se não achar JSON válido, devolve uma única subtarefa (degrada, não quebra)."""
    match = re.search(r"\{[\s\S]*\}", raw)
    subtasks: list[dict] = []
    if match:
        try:
            obj = json.loads(match.group(0))
            for st in obj.get("subtasks", [])[:limit]:
                sid = str(st.get("id", "")).strip()
                goal = str(st.get("goal", "")).strip()
                if sid and goal:
                    deps = [str(d).strip() for d in st.get("deps", []) if str(d).strip()]
                    subtasks.append({"id": sid, "goal": goal, "deps": deps})
        except json.JSONDecodeError:
            pass
    return sanitize_dag(subtasks)


def sanitize_dag(subtasks: list[dict]) -> list[dict]:
    """Remove ids duplicados, deps órfãs e auto-referência. Se sobrar ciclo, é
    tratado no executor (não há progresso -> erro claro)."""
    seen: set[str] = set()
    clean: list[dict] = []
    for st in subtasks:
        if st["id"] in seen:
            continue
        seen.add(st["id"])
        clean.append(st)
    valid_ids = {st["id"] for st in clean}
    for st in clean:
        st["deps"] = [d for d in st["deps"] if d in valid_ids and d != st["id"]]
    return clean


async def execute_dag(subtasks: list[dict], run_subtask, on_event=None) -> dict:
    """Executa o DAG por níveis: a cada rodada, roda EM PARALELO (asyncio.gather)
    todas as subtarefas cujas dependências já terminaram. `run_subtask(st,
    dep_results)` é injetável (LLM real ou fake de teste). Devolve {id: resultado}.

    Detecção de ciclo/travamento: se numa rodada nenhuma subtarefa está pronta e
    ainda há pendentes, é ciclo (ou dep pra id inexistente) — levanta ValueError
    em vez de rodar pra sempre.
    """
    results: dict[str, str] = {}
    pending = {st["id"]: st for st in subtasks}

    while pending:
        ready = [st for st in pending.values() if all(d in results for d in st["deps"])]
        if not ready:
            raise ValueError(f"dependência cíclica ou inexistente entre: {sorted(pending)}")

        if on_event:
            on_event("level", ids=[st["id"] for st in ready])

        async def _one(st):
            dep_results = {d: results[d] for d in st["deps"]}
            out = await run_subtask(st, dep_results)
            return st["id"], out

        # AQUI está a paralelização: todas as subtarefas prontas juntas.
        done = await asyncio.gather(*[_one(st) for st in ready])
        for sid, out in done:
            results[sid] = out
            pending.pop(sid, None)
            if on_event:
                on_event("subtask_done", id=sid)

    return results


# ---------------- Camada HTTP (SSE) ----------------

_PLAN_PROMPT = (
    "Quebre a tarefa abaixo em até {n} subtarefas para resolver EM PARALELO quando possível. "
    "Declare dependências só quando uma subtarefa REALMENTE precisa do resultado de outra. "
    "Responda SÓ com JSON: {{\"subtasks\":[{{\"id\":\"s1\",\"goal\":\"...\",\"deps\":[]}}, "
    "{{\"id\":\"s2\",\"goal\":\"...\",\"deps\":[\"s1\"]}}]}}.\n\nTarefa: {task}"
)


@router.post("/orchestrate")
async def orchestrate(
    body: OrchestrateIn,
    x_or_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    key = resolve_key(x_or_key or authorization)
    limit = max(2, min(body.max_subtasks, _MAX_SUBTASKS))

    async def gen():
        events: list[str] = []

        def sse(event: str, **data) -> str:
            return "data: " + json.dumps({"event": event, **data}, ensure_ascii=False) + "\n\n"

        try:
            if not key:
                yield sse("error", message="Sem chave do OpenRouter. Configure a chave no site.")
                return

            yield sse("status", message="Planejando subtarefas…")
            plan_raw = await chat(
                [{"role": "user", "content": _PLAN_PROMPT.format(n=limit, task=body.task)}],
                key=key, model=body.model,
            )
            subtasks = parse_plan(content_of(plan_raw), limit)
            if not subtasks:
                subtasks = [{"id": "s1", "goal": body.task, "deps": []}]
            yield sse("plan", subtasks=subtasks)

            # roda uma subtarefa: (opcional) busca web + 1 chamada ao LLM com os
            # resultados das dependências no contexto.
            async def run_subtask(st, dep_results):
                context = ""
                if dep_results:
                    context = "\n\nResultados das subtarefas anteriores das quais esta depende:\n" + \
                        "\n\n".join(f"[{k}]: {v}" for k, v in dep_results.items())
                web_ctx = ""
                if body.web:
                    try:
                        hits = await web_search(st["goal"], 4)
                        web_ctx = "\n\nBusca web:\n" + "\n".join(
                            f"- {h['title']} ({h['url']}): {h['snippet']}" for h in hits)
                    except Exception:  # noqa: BLE001 — busca é best-effort
                        web_ctx = ""
                ans = content_of(await chat(
                    [{"role": "user", "content":
                      f"Subtarefa: {st['goal']}{context}{web_ctx}\n\n"
                      f"Responda de forma objetiva e concreta, citando fontes (links) quando houver."}],
                    key=key, model=body.model,
                ))
                return ans

            # coleta eventos do executor pra transmitir (execute_dag é síncrono
            # nos callbacks; acumula e emite entre os awaits).
            emitted: list[tuple] = []
            results = await execute_dag(
                subtasks, run_subtask,
                on_event=lambda ev, **d: emitted.append((ev, d)),
            )
            for ev, d in emitted:
                yield sse(ev, **d)
            for sid, out in results.items():
                yield sse("result", id=sid, answer=out)

            yield sse("status", message="Sintetizando…")
            joined = "\n\n".join(f"### {st['id']}: {st['goal']}\n{results.get(st['id'], '')}" for st in subtasks)
            final = content_of(await chat(
                [{"role": "user", "content":
                  f"Tarefa original: {body.task}\n\nResultados das subtarefas:\n{joined}\n\n"
                  f"Sintetize uma resposta final única em markdown (## seções, **negrito**, "
                  f"listas), integrando tudo e citando as fontes. Seja honesto sobre incertezas."}],
                key=key, model=body.model,
            ))
            yield sse("synthesis", markdown=final)
            yield sse("done")
        except ValueError as exc:
            yield sse("error", message=f"Plano inválido: {exc}")
        except Exception as exc:  # noqa: BLE001
            yield sse("error", message=str(exc))

    return StreamingResponse(gen(), media_type="text/event-stream")
