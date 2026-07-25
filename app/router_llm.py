"""RouteLLM no backend — um modelo barato escolhe qual modelo resolve a tarefa.

Isto é a Fase 1 do prompt mestre ("roteamento em camada: classificador → modelo
certo"). O plano original falava em Groq como classificador; como tudo passa pelo
OpenRouter, o classificador aqui é um modelo GRÁTIS do próprio catálogo — mesma
ideia, custo zero, uma conta a menos.

As regras (shortlist de candidatos, papel de cada modelo, prompt do
classificador, par do Fusion) são as que o painel já usava em
VTz-painel/src/js — foram trazidas pra cá, não reinventadas. O ganho de mover
pro backend é que as quatro frentes (site, extensão, JARVIS, Electron) passam a
rotear igual, em vez de só o site.

Três modos:
  auto    → escolhe entre os modelos fortes e baratos, equilibrando custo
  free    → escolhe só entre modelos grátis
  fusion  → dois modelos respondem em paralelo e um terceiro funde
"""
import json

from .openrouter import chat, content_of

# Candidatos do modo "auto": padrão de id -> papel que ele cumpre. A ordem
# importa (o primeiro que existir no catálogo entra). Igual ao painel.
_WANTED = [
    ("claude-opus", "código complexo, arquitetura, análise profunda"),
    ("claude-sonnet", "código, escrita técnica, raciocínio"),
    ("gpt-5", "raciocínio geral avançado"),
    ("deepseek-r1", "raciocínio matemático, custo baixo"),
    ("gemini-3.5-flash", "tarefas médias, rápido e barato"),
    ("gemini-2.5-flash", "conversas simples, muito barato"),
    (":free", "tarefas triviais, grátis"),
]

_MAX_FREE = 12          # teto de candidatos grátis, pra não estourar o prompt


def is_free(m: dict) -> bool:
    if str(m.get("id", "")).endswith(":free"):
        return True
    p = m.get("pricing") or {}
    try:
        return float(p.get("prompt") or 0) == 0 and float(p.get("completion") or 0) == 0
    except (TypeError, ValueError):
        return False


def is_image(m: dict) -> bool:
    """Modelo de imagem não serve pra responder texto — fica fora do roteamento."""
    arch = m.get("architecture") or {}
    outs = arch.get("output_modalities")
    if not outs:
        modality = arch.get("modality") or ""
        outs = modality.split("->")[-1].split("+") if "->" in modality else []
    return "image" in (outs or [])


def _free_role(model_id: str) -> str:
    """Papel inferido do id, pros modelos grátis (eles não vêm rotulados)."""
    s = model_id.lower()
    if any(k in s for k in ("r1", "reason", "think")):
        return "raciocínio e matemática"
    if "coder" in s or "code" in s:
        return "código"
    if any(k in s for k in ("70b", "72b", "large", "405b")):
        return "tarefas complexas"
    if any(k in s for k in ("mini", "small", "8b", "flash")):
        return "conversas rápidas"
    return "uso geral"


def candidates(models: list[dict], free_only: bool) -> list[dict]:
    """Shortlist de modelos reais do catálogo, cada um com o seu papel."""
    texto = [m for m in models if not is_image(m)]

    if free_only:
        livres = [m for m in texto if is_free(m)][:_MAX_FREE]
        return [{"id": m["id"], "role": _free_role(m["id"])} for m in livres]

    escolhidos: list[dict] = []
    for padrao, papel in _WANTED:
        achado = next((m for m in texto if padrao in m["id"]), None)
        if achado and not any(c["id"] == achado["id"] for c in escolhidos):
            escolhidos.append({"id": achado["id"], "role": papel})
    return escolhidos


def classifier_model(models: list[dict]) -> str | None:
    """Quem classifica é sempre um modelo grátis — roteamento não deve custar."""
    livre = next((m for m in models if is_free(m) and not is_image(m)), None)
    return livre["id"] if livre else None


_PROMPT = (
    "Você é um roteador de modelos de IA. Analise a tarefa do usuário e escolha o "
    "MELHOR modelo da lista abaixo, equilibrando qualidade e custo (não escolha "
    "modelo caro pra tarefa trivial).\n{lista}\n"
    'Responda APENAS com JSON válido: {{"model":"<id exato da lista>"}}'
)


async def classify(task: str, models: list[dict], key: str, free_only: bool) -> str | None:
    """Devolve o id do modelo escolhido, ou None se não deu pra decidir.

    O id é validado contra a shortlist: se o classificador alucinar um nome que
    não está na lista, a escolha é descartada. Melhor cair no modelo padrão do
    que mandar a conversa pra um id que não existe.
    """
    lista = candidates(models, free_only)
    if not lista:
        return None
    classificador = classifier_model(models)
    if not classificador:
        return None

    texto = "\n".join(f"- {c['id']} ({c['role']})" for c in lista)
    try:
        resposta = await chat(
            [
                {"role": "system", "content": _PROMPT.format(lista=texto)},
                {"role": "user", "content": task[:2000]},
            ],
            key=key, model=classificador,
        )
        cru = content_of(resposta).replace("```json", "").replace("```", "").strip()
        escolhido = json.loads(cru).get("model")
    except Exception:  # noqa: BLE001 — classificador é best-effort; falhar não derruba o chat
        return None

    return escolhido if any(c["id"] == escolhido for c in lista) else None


def fusion_pair(models: list[dict]) -> list[str]:
    """Um modelo forte + um rápido, distintos. O Fusion pede aos dois em paralelo."""
    texto = [m for m in models if not is_image(m)]
    forte = next((m for m in texto if any(
        k in m["id"] for k in ("claude-opus", "gpt-5.5", "claude-sonnet-5", "gemini-3"))), None) \
        or next((m for m in texto if not is_free(m)), None)
    rapido = next((m for m in texto if any(
        k in m["id"] for k in ("deepseek", "gemini-2.5-flash", "gpt-5-mini", "llama-3.3"))
        and (not forte or m["id"] != forte["id"])), None) \
        or next((m for m in texto if not forte or m["id"] != forte["id"]), None)
    return [m["id"] for m in (forte, rapido) if m]


_FUSAO = (
    "Abaixo estão duas respostas independentes para a mesma pergunta. Produza UMA "
    "resposta final melhor que as duas: mantenha o que cada uma acertou, corrija o "
    "que divergir, remova repetição. Não comente o processo nem cite as respostas "
    "como 'resposta 1/2' — entregue só o resultado final.\n\n"
    "PERGUNTA:\n{pergunta}\n\n--- A ---\n{a}\n\n--- B ---\n{b}"
)


async def run_fusion(messages: list[dict], models: list[dict], key: str):
    """Pede a dois modelos em paralelo e funde. Gera eventos, não retorna texto.

    Em paralelo de verdade (asyncio.gather): o tempo total é o do modelo mais
    lento, não a soma dos dois. Se um falhar, segue com o que respondeu — duas
    falhas viram erro.
    """
    import asyncio

    par = fusion_pair(models)
    if len(par) < 2:
        yield {"type": "error", "message": "Preciso de ao menos 2 modelos no catálogo pra fundir."}
        return

    yield {"type": "route", "mode": "fusion", "models": par}

    async def uma(model_id):
        try:
            return content_of(await chat(messages, key=key, model=model_id))
        except Exception:  # noqa: BLE001 — uma falha não invalida a outra resposta
            return None

    respostas = await asyncio.gather(*[uma(m) for m in par])
    validas = [(par[i], r) for i, r in enumerate(respostas) if r]

    if not validas:
        yield {"type": "error", "message": "Nenhum dos dois modelos respondeu."}
        return
    if len(validas) == 1:
        # sem par não há o que fundir: entrega o que veio, dizendo que foi só um
        yield {"type": "route", "mode": "fusion", "models": [validas[0][0]],
               "note": "só um dos modelos respondeu; entregando sem fundir"}
        yield {"type": "answer", "text": validas[0][1]}
        return

    pergunta = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
    fusor = classifier_model(models) or par[0]
    try:
        final = content_of(await chat(
            [{"role": "user", "content": _FUSAO.format(
                pergunta=pergunta, a=validas[0][1], b=validas[1][1])}],
            key=key, model=fusor,
        ))
    except Exception:  # noqa: BLE001 — sem fusor, a melhor resposta isolada serve
        final = max((r for _, r in validas), key=len)

    yield {"type": "answer", "text": final}
