"""Teste do orquestrador planeja→paraleliza→sintetiza (núcleo execute_dag).

Roda sem pytest:  python3 tests/test_orchestrate.py

Prova, sem LLM nem rede (run_subtask injetado):
  - subtarefas INDEPENDENTES rodam de fato em PARALELO (sobreposição no tempo)
  - subtarefa dependente só começa DEPOIS da dependência terminar
  - resultados das dependências chegam no contexto da dependente
  - ciclo/dep inexistente é detectado (não roda pra sempre)
  - parse_plan/sanitize_dag limpam ids duplicados e deps órfãs
"""
import asyncio
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from app.routers.orchestrate import execute_dag, parse_plan, sanitize_dag  # noqa: E402

_fails = 0


def check(cond, label):
    global _fails
    print(("  ok  " if cond else " FAIL ") + label)
    if not cond:
        _fails += 1


async def _run():
    # ---- paralelismo real de subtarefas independentes ----
    print("== independentes rodam em paralelo ==")
    timeline = []

    async def slow_subtask(st, dep_results):
        timeline.append(("start", st["id"], time.monotonic()))
        await asyncio.sleep(0.2)
        timeline.append(("end", st["id"], time.monotonic()))
        return f"resultado-{st['id']}"

    subs = [{"id": "a", "goal": "A", "deps": []}, {"id": "b", "goal": "B", "deps": []},
            {"id": "c", "goal": "C", "deps": []}]
    t0 = time.monotonic()
    results = await execute_dag(subs, slow_subtask)
    elapsed = time.monotonic() - t0
    check(len(results) == 3, "3 subtarefas concluídas")
    # se fosse sequencial seriam ~0.6s; em paralelo ~0.2s. Folga generosa: < 0.4s.
    check(elapsed < 0.4, f"3 independentes em paralelo (~0.2s, não 0.6s) — levou {elapsed:.2f}s")
    starts = [e[2] for e in timeline if e[0] == "start"]
    check(max(starts) - min(starts) < 0.1, "as 3 começaram praticamente juntas")

    # ---- dependência respeita a ordem ----
    print("== dependente espera a dependência ==")
    order = []

    async def track_subtask(st, dep_results):
        order.append(st["id"])
        await asyncio.sleep(0.05)
        # a subtarefa 'dep' deve receber o resultado de 'base' no contexto
        if st["id"] == "dep":
            check("base" in dep_results and dep_results["base"] == "resultado-base",
                  "dependente recebeu o resultado da dependência no contexto")
        return f"resultado-{st['id']}"

    subs2 = [{"id": "base", "goal": "base", "deps": []},
             {"id": "dep", "goal": "dep", "deps": ["base"]}]
    await execute_dag(subs2, track_subtask)
    check(order == ["base", "dep"], f"ordem respeitou a dependência (veio {order})")

    # ---- ciclo é detectado ----
    print("== ciclo detectado ==")
    cyclic = [{"id": "x", "goal": "x", "deps": ["y"]}, {"id": "y", "goal": "y", "deps": ["x"]}]
    try:
        await execute_dag(cyclic, slow_subtask)
        check(False, "deveria ter levantado ValueError no ciclo")
    except ValueError:
        check(True, "ciclo levanta ValueError (não roda pra sempre)")


def _sync_checks():
    print("== parse_plan / sanitize_dag ==")
    raw = '{"subtasks":[{"id":"a","goal":"fazer A","deps":[]},{"id":"a","goal":"dup","deps":[]},' \
          '{"id":"b","goal":"fazer B","deps":["a","fantasma"]}]}'
    plan = parse_plan(raw, 8)
    ids = [s["id"] for s in plan]
    check(ids == ["a", "b"], f"id duplicado removido (veio {ids})")
    b = next(s for s in plan if s["id"] == "b")
    check(b["deps"] == ["a"], f"dep órfã 'fantasma' removida (veio {b['deps']})")

    # auto-referência removida
    clean = sanitize_dag([{"id": "z", "goal": "z", "deps": ["z"]}])
    check(clean[0]["deps"] == [], "auto-dependência removida")

    # JSON inválido degrada pra lista vazia (o endpoint cai numa subtarefa única)
    check(parse_plan("isto não é json", 8) == [], "texto sem JSON -> plano vazio (degrada, não quebra)")


def main():
    _sync_checks()
    asyncio.run(_run())
    if _fails:
        print(f"\n{_fails} CHECK(S) FALHARAM ✗")
        sys.exit(1)
    print("\nTODOS OS CHECKS PASSARAM ✓")


if __name__ == "__main__":
    main()
