"""/api/autonomous — agente autônomo avançado (planeja → age → observa → entrega).

Diferente do /api/agent (loop leve de 2 ferramentas), aqui o modelo trabalha como
um agente de verdade: faz um PLANO, executa ferramentas em várias rodadas guardando
notas numa memória de trabalho, RE-PLANEJA sozinho quando descobre algo novo, e só
então entrega. Transmite cada passo por SSE pro site mostrar ao vivo.

Honestidade: "autônomo" aqui = decide sozinho quais ferramentas usar e quando parar,
dentro de tetos rígidos (passos e tokens) pra NÃO torrar a chave do usuário. Não é um
agente que opera o navegador/preenche formulários (isso exige um runtime tipo Manus/
Perplexity Computer — fora do escopo de um backend HTTP). O que ele opera de verdade:
busca web, leitura de páginas, e os conectores já configurados (Notion).

Custo: cada passo é uma chamada ao OpenRouter → gasta tokens. Use um modelo forte em
tool-calling (ex.: openai/gpt-4.1) — modelos fracos erram a escolha de ferramenta e
desperdiçam passos. O teto de passos (max_steps) é a trava dura contra gasto infinito.
"""
import json

import httpx
from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import settings
from ..contexto import comprime
from ..openrouter import chat, resolve_key
from ..services import scrape_url, web_search
from ..skills import carrega_pasta, corpo_seguro, instrucao_do_catalogo
from .. import store

# Catálogo carregado uma vez, na subida. Só as FICHAS entram no prompt; o corpo
# de cada skill é carregado sob demanda pela ferramenta `usar_skill`.
#
# É a diferença entre 74 e 381 tokens com três skills — e com quarenta, entre
# uma linha por skill e a conversa inteira. Ver app/skills.py.
_SKILLS, _SKILLS_PROBLEMAS = carrega_pasta()

# Teto de contexto do laço autônomo.
#
# ESCOLHIDO MEDINDO, não por instinto. A primeira tentativa foi 24000 — número
# que vinha de "cabe em qualquer modelo do catálogo", que é outro problema.
# Numa tarefa de 12 passos lendo arquivos, economizava 12%: o teto era tão alto
# que a compressão quase nunca disparava.
#
# A medição, mesma tarefa, somando os tokens de ENTRADA das 12 voltas
# (208 mil sem compressão):
#
#     teto     enviados   economia   contexto vivo no fim
#     24000     184.026        12%                 23.254
#     16000     113.746        45%                 13.214
#     12000      97.682        53%                  9.198   <- escolhido
#      8000      76.550        63%                  7.651
#      4000      46.951        77%                  3.963
#
# 12000 corta mais da metade do custo e ainda deixa ~9 mil tokens de histórico
# vivo, que é bastante pra um agente no meio de uma tarefa. Descer mais compra
# economia com burrice, e resposta ruim custa a rodada inteira de novo.
TETO_CONTEXTO_TOKENS = 12000

router = APIRouter()


class AutonomousIn(BaseModel):
    task: str
    model: str | None = None
    max_steps: int = 12          # trava dura: nº máx. de rodadas do loop
    max_tokens_budget: int = 0   # teto opcional de tokens acumulados (0 = sem teto)


# ---------------- Ferramentas expostas ao modelo ----------------
# note/update_plan/finish operam sobre o ESTADO do agente (memória de trabalho e
# plano), não sobre a rede — é o que dá o comportamento "agente" de verdade.
TOOLS = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Busca na web (títulos, links, trechos). Use pra descobrir fontes.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "fetch_url",
        "description": "Baixa uma página e extrai título, descrição, imagem e texto. "
                       "Use pra ler a fundo uma fonte achada na busca.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "notion_search",
        "description": "Busca páginas/bancos no Notion do usuário (se o conector estiver "
                       "configurado). Use quando a tarefa envolver as notas dele.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "note",
        "description": "Guarda um fato/achado na sua memória de trabalho pra usar na "
                       "resposta final. Anote conforme descobre, não deixe pro fim.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "update_plan",
        "description": "Reescreve seu plano de passos quando descobrir algo que muda a "
                       "rota. Passe a lista completa e atualizada de passos.",
        "parameters": {"type": "object", "properties": {
            "steps": {"type": "array", "items": {"type": "string"}}}, "required": ["steps"]}}},
    {"type": "function", "function": {
        "name": "usar_skill",
        "description": "Carrega as instruções completas de uma habilidade do catálogo. "
                       "Use quando o nome e a descrição indicarem que ela serve pra tarefa. "
                       "Chame ANTES de executar o trabalho que ela descreve.",
        "parameters": {"type": "object", "properties": {
            "nome": {"type": "string", "description": "nome exato, como aparece no catálogo"}},
            "required": ["nome"]}}},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Encerra a tarefa e entrega a resposta final em markdown. Só chame "
                       "quando tiver o suficiente pra responder bem.",
        "parameters": {"type": "object", "properties": {
            "answer": {"type": "string"}}, "required": ["answer"]}}},
]

_SYSTEM = (
    "Você é um agente autônomo. Recebe uma tarefa e a resolve sozinho: primeiro pensa "
    "num plano, depois USA AS FERRAMENTAS em várias rodadas até ter material suficiente, "
    "e só então chama `finish` com a resposta final.\n\n"
    "Regras:\n"
    "1. A cada rodada, ou você chama uma ferramenta, ou chama `finish`. Não responda em "
    "texto puro no meio do caminho.\n"
    "2. Anote achados com `note` conforme descobre — a resposta final se apoia nessas notas.\n"
    "3. Se uma ferramenta falhar, leia o erro e tente outra rota (outra busca, outra URL). "
    "Não repita a mesma chamada que já falhou.\n"
    "4. Ajuste o plano com `update_plan` se descobrir algo que muda a rota.\n"
    "5. Seja eficiente: você tem um teto de passos. Não desperdice rodadas.\n"
    "6. Na resposta final (`finish`): markdown com ## seções, **negrito**, listas, e cite "
    "as fontes (links) que você leu. Seja honesto sobre o que ficou incerto."
)


async def _notion_search(query: str) -> str:
    token = store.get_secret("notion_token")
    if not token:
        return "Notion não configurado (sem token). Não use esta ferramenta nesta tarefa."
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        resp = await client.post(
            "https://api.notion.com/v1/search",
            headers={"Authorization": f"Bearer {token}",
                     "Notion-Version": "2022-06-28", "Content-Type": "application/json"},
            json={"query": query} if query else {},
        )
    if resp.status_code >= 400:
        return f"Erro do Notion {resp.status_code}: {resp.text[:300]}"
    results = resp.json().get("results", [])
    out = []
    for r in results[:5]:
        props = r.get("properties", {})
        title = ""
        for v in props.values():
            if v.get("type") == "title":
                title = "".join(t.get("plain_text", "") for t in v.get("title", []))
                break
        out.append({"id": r.get("id"), "title": title or "(sem título)", "url": r.get("url")})
    return json.dumps(out, ensure_ascii=False) or "(nada encontrado)"


async def _run_tool(name: str, args: dict, state: dict) -> str:
    """Executa uma ferramenta. NUNCA levanta exceção — erro vira texto de observação,
    pra o modelo decidir o que fazer (recuperação de erro)."""
    try:
        if name == "web_search":
            hits = await web_search(args.get("query", ""), 5)
            return json.dumps(hits, ensure_ascii=False)[:3500] or "(sem resultados)"
        if name == "fetch_url":
            return json.dumps(await scrape_url(args.get("url", "")), ensure_ascii=False)[:3500]
        if name == "notion_search":
            return await _notion_search(args.get("query", ""))
        if name == "usar_skill":
            # `corpo_seguro` e não `registro.corpo`: uma skill é texto de
            # terceiro entrando no laço de decisão, então passa pelo escâner de
            # injeção antes de chegar ao modelo. E a recusa vira observação
            # legível, não exceção — o agente pode seguir sem a skill.
            corpo, motivo = corpo_seguro(_SKILLS, args.get("nome", ""))
            if corpo is None:
                return f"Não foi possível usar essa habilidade: {motivo}"
            return (f"[instruções da habilidade '{args.get('nome')}'"
                    + (f" — {motivo}" if motivo else "") + "]\n" + corpo)
        if name == "note":
            txt = (args.get("text") or "").strip()
            if txt:
                state["notes"].append(txt)
            return f"Anotado. ({len(state['notes'])} nota(s) na memória.)"
        if name == "update_plan":
            steps = [s for s in (args.get("steps") or []) if isinstance(s, str) and s.strip()]
            if steps:
                state["plan"] = steps
            return "Plano atualizado."
        return f"Ferramenta desconhecida: {name}"
    except Exception as exc:  # noqa: BLE001 — de propósito: erro vira observação
        return f"ERRO ao rodar {name}: {exc}. Tente outra abordagem."


@router.post("/autonomous")
async def autonomous(
    body: AutonomousIn,
    x_or_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    key = resolve_key(x_or_key or authorization)
    max_steps = max(1, min(body.max_steps, 30))  # nunca mais que 30, por segurança

    async def gen():
        def sse(event: str, **data) -> str:
            return "data: " + json.dumps({"event": event, **data}, ensure_ascii=False) + "\n\n"

        state = {"plan": [], "notes": []}
        usage_total = {"prompt": 0, "completion": 0, "total": 0}
        recent_calls: list[str] = []  # pra detectar repetição (anti-laço)
        avisos_laco = 0               # dois avisos ignorados e o laço é interrompido

        try:
            if not key:
                yield sse("error", message="Sem chave do OpenRouter. Configure a chave no site.")
                return

            # ---- 1) Plano inicial ----
            yield sse("status", message="Planejando…")
            plan_raw = await chat(
                [{"role": "user", "content":
                  f"Tarefa: {body.task}\n\nListe de 3 a 6 passos objetivos pra resolver isso. "
                  f"Responda SÓ com um array JSON de strings."}],
                key=key, model=body.model,
            )
            _acc_usage(plan_raw, usage_total)
            state["plan"] = _parse_steps(plan_raw)
            yield sse("plan", steps=state["plan"])
            yield sse("usage", **usage_total)

            # ---- 2) Loop de execução ----
            messages = [
                # O catálogo de habilidades entra aqui, não numa constante:
                # assim uma skill acrescentada na pasta vale sem reiniciar o
                # módulo, e o prompt continua sendo montado num lugar só.
                {"role": "system", "content": _SYSTEM + (
                    "\n\n" + instrucao_do_catalogo(_SKILLS) if len(_SKILLS) else "")},
                {"role": "user", "content":
                 f"Tarefa: {body.task}\n\nSeu plano inicial:\n" +
                 "\n".join(f"{i+1}. {s}" for i, s in enumerate(state["plan"]))},
            ]

            for step in range(max_steps):
                # COMPRESSÃO ANTES DE CADA VOLTA.
                #
                # É aqui que o dinheiro vaza: a lista inteira é reenviada a cada
                # passo, então o primeiro prompt é cobrado `max_steps` vezes — e
                # as observações de ferramenta que entram no meio (conteúdo de
                # arquivo, resultado de busca) são as maiores mensagens da
                # conversa. O custo cresce com o quadrado dos passos.
                #
                # O relatório vai pro fio: comprimir em silêncio esconderia a
                # causa de uma resposta pior, porque o modelo passa a não ver
                # algo que via e ninguém liga uma coisa à outra.
                messages, rel_ctx = comprime(messages, teto_tokens=TETO_CONTEXTO_TOKENS)
                if rel_ctx.comprimiu:
                    yield sse("contexto", detalhe=str(rel_ctx),
                              economia=rel_ctx.economia, coube=rel_ctx.coube)
                data = await chat(messages, key=key, model=body.model, tools=TOOLS)
                _acc_usage(data, usage_total)
                message = data["choices"][0]["message"]
                messages.append(message)
                calls = message.get("tool_calls")

                # Modelo respondeu em texto sem chamar ferramenta → trata como entrega.
                if not calls:
                    answer = message.get("content", "") or "(o agente parou sem resposta)"
                    yield sse("answer", markdown=answer)
                    yield sse("usage", **usage_total)
                    yield sse("done")
                    return

                for call in calls:
                    fn = call["function"]["name"]
                    try:
                        args = json.loads(call["function"].get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}

                    # Entrega final
                    if fn == "finish":
                        yield sse("answer", markdown=args.get("answer", "") or "(sem resposta)")
                        yield sse("usage", **usage_total)
                        yield sse("done")
                        return

                    # Anti-laço: repetição direta, alternância ou ciclo curto.
                    # Janela de 8 (era 4) porque ciclo de 3 precisa de 6 pra ser
                    # visto, e 4 o escondia por completo.
                    sig = fn + json.dumps(args, sort_keys=True, ensure_ascii=False)
                    recent_calls.append(sig)
                    recent_calls[:] = recent_calls[-8:]
                    motivo_laco = detecta_laco(recent_calls)

                    if motivo_laco:
                        avisos_laco += 1
                        # Avisar é a primeira tentativa: o modelo às vezes muda
                        # de abordagem. Mas quem ignora duas vezes não vai mudar,
                        # e cada rodada extra é dinheiro — então encerra com o
                        # que já tem, em vez de queimar o teto de passos girando.
                        if avisos_laco >= LACO_AVISOS_ATE_PARAR:
                            yield sse("observation", tool=fn,
                                      result=f"[laço interrompido] {motivo_laco}")
                            texto = (message.get("content") or "").strip()
                            yield sse("answer", markdown=texto or (
                                "Parei porque entrei num laço: " + motivo_laco +
                                ". O que consegui apurar está acima."))
                            yield sse("usage", **usage_total)
                            yield sse("done")
                            return
                        obs = (f"Você {motivo_laco}. Mude de abordagem ou chame "
                               "`finish` com o que já tem.")
                    else:
                        yield sse("thought", text=(message.get("content") or "").strip())
                        yield sse("action", tool=fn, args=args, step=step + 1)
                        obs = await _run_tool(fn, args, state)
                        yield sse("observation", tool=fn, result=obs[:800])

                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": obs})

                # Reflete plano/notas atualizados de volta pro site
                if state["plan"]:
                    yield sse("plan", steps=state["plan"])
                yield sse("usage", **usage_total)

                # Teto de tokens (opcional): força finalização se estourar
                if body.max_tokens_budget and usage_total["total"] >= body.max_tokens_budget:
                    yield sse("status", message="Teto de tokens atingido — finalizando com o que já tem.")
                    break

            # ---- 3) Chegou no limite de passos/tokens sem `finish`: força a entrega ----
            notes = "\n".join(f"- {n}" for n in state["notes"]) or "(sem notas coletadas)"
            final = await chat(
                messages + [{"role": "user", "content":
                    "Você atingiu o limite. Entregue AGORA a melhor resposta final possível "
                    "em markdown, com base no que já descobriu. Notas coletadas:\n" + notes}],
                key=key, model=body.model,
            )
            _acc_usage(final, usage_total)
            yield sse("answer", markdown=(final["choices"][0]["message"].get("content") or notes),
                      note="limite de passos atingido")
            yield sse("usage", **usage_total)
            yield sse("done")
        except httpx.HTTPStatusError as exc:
            yield sse("error", message=f"OpenRouter {exc.response.status_code}: {exc.response.text[:300]}")
        except Exception as exc:  # noqa: BLE001
            yield sse("error", message=str(exc))

    return StreamingResponse(gen(), media_type="text/event-stream")


# Quantos avisos de laço antes de encerrar à força. Dois porque o primeiro pode
# ser aproveitado: o modelo às vezes muda de abordagem quando avisado. Se
# ignorar duas vezes, não vai mudar — e cada rodada extra é dinheiro.
LACO_AVISOS_ATE_PARAR = 2


def detecta_laco(assinaturas: list[str]) -> str | None:
    """O agente está girando em falso? Devolve o motivo, ou None.

    Puro e sem I/O de propósito — dá pra testar todos os padrões sem tocar em
    rede nem no OpenRouter, que é o mesmo princípio que o /api/orchestrate já
    aplica ao separar o núcleo da camada HTTP.

    POR QUE O TETO DE PASSOS NÃO BASTA

    `max_steps` pega o laço óbvio. Não pega o caso comum: o agente chama a mesma
    ferramenta com argumento levemente diferente, parecendo progredir, e gasta o
    orçamento inteiro sem sair do lugar. Num projeto com R$ 50/mês, um agente em
    laço queima a cota do mês numa madrugada.

    TRÊS PADRÕES, E O SEGUNDO É O QUE ESCAPAVA

    1. Repetição direta — a mesma chamada N vezes. Já era detectada.
    2. Alternância (A,B,A,B) — cada assinatura aparece só 2 vezes, então a
       contagem simples nunca disparava. É o padrão mais comum quando o modelo
       "verifica" um resultado chamando a ferramenta anterior de novo.
    3. Ciclo de três (A,B,C,A,B,C) — escapava inteiro.

    Compara SEQUÊNCIAS e não frequências: um ciclo pode ter todas as chamadas
    com frequência baixa e ainda assim não progredir nunca.
    """
    n = len(assinaturas)
    if n < 3:
        return None

    if assinaturas[-3:].count(assinaturas[-1]) >= 3:
        return "repetiu a mesma chamada três vezes seguidas"

    # Ciclo de período 2 ou 3: os últimos p elementos iguais aos p anteriores.
    for p in (2, 3):
        if n >= p * 2 and assinaturas[-p:] == assinaturas[-2 * p:-p]:
            return f"está repetindo um ciclo de {p} chamadas sem progredir"

    return None


def _parse_steps(data: dict) -> list[str]:
    raw = data["choices"][0]["message"].get("content", "") or ""
    import re
    match = re.search(r"\[[\s\S]*\]", raw)
    if match:
        try:
            arr = json.loads(match.group(0))
            steps = [s.strip() for s in arr if isinstance(s, str) and s.strip()]
            if steps:
                return steps[:8]
        except json.JSONDecodeError:
            pass
    lines = [re.sub(r"^[-*\d.\s]+", "", ln).strip() for ln in raw.splitlines()]
    return [ln for ln in lines if len(ln) > 3][:8] or ["Resolver a tarefa"]


def _acc_usage(data: dict, total: dict):
    u = data.get("usage") or {}
    total["prompt"] += u.get("prompt_tokens", 0)
    total["completion"] += u.get("completion_tokens", 0)
    total["total"] += u.get("total_tokens", 0)
