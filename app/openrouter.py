"""Ponte com a API de chat do OpenRouter.

A chave do OpenRouter NUNCA é gravada no servidor: o site envia a chave do usuário
no header (X-OR-Key ou Authorization). Só se nada vier, cai no valor do .env.
Assim mantemos o princípio do projeto: a chave vive no navegador do usuário.

Duas formas de chamar: `chat` (espera a resposta inteira) e `chat_stream`
(devolve os pedaços conforme chegam). O JARVIS usa o streaming pro texto
aparecer aos poucos no painel; o resto do backend segue usando `chat`.
"""
import json
import time

import httpx

from . import telemetria
from .config import settings


def resolve_key(header_value: str | None) -> str:
    key = (header_value or "").strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key or settings.openrouter_api_key


def ollama_ready() -> bool:
    """Fallback local está configurado? (Seção 5 — Ollama)"""
    return bool(settings.ollama_base and settings.ollama_model)


async def _post_chat(base: str, payload: dict, headers: dict) -> dict:
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        resp = await client.post(f"{base}/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def chat(messages: list[dict], key: str, model: str | None = None,
               tools: list | None = None, plugins: list | None = None,
               origem: str = "chat") -> dict:
    """Fala com o OpenRouter. Se não houver chave (ou a chamada falhar) e existir
    um Ollama configurado, cai nele — e marca `_provider` na resposta, pra quem
    chamou poder dizer ao usuário quem respondeu de verdade.

    Sem chave E sem fallback, levanta. Silenciar isso faria o usuário achar que
    falou com um modelo forte quando não falou com nenhum.
    """
    payload: dict = {"model": model or settings.default_model, "messages": messages}
    if tools:
        payload["tools"] = tools
    if plugins:
        payload["plugins"] = plugins

    async def _local() -> dict:
        local = dict(payload, model=settings.ollama_model)
        local.pop("plugins", None)          # extensão do OpenRouter; local não entende
        data = await _post_chat(settings.ollama_base.rstrip("/"), local,
                                {"Content-Type": "application/json"})
        data["_provider"] = "ollama"
        return data

    inicio = time.monotonic()

    async def _mede(data: dict) -> dict:
        """Registra a chamada que deu certo. Fica DENTRO do `chat` porque o
        provedor real só é conhecido aqui — o fallback pro Ollama acontece no
        meio, e medir por fora atribuiria o custo ao provedor errado."""
        prov = data.get("_provider", "?")
        mdl = settings.ollama_model if prov == "ollama" else (model or settings.default_model)
        ent, sai = telemetria.uso_de(data)
        # Local é de graça de verdade: 0.0, não None. Ver a regra 2 do módulo.
        custo = 0.0 if prov == "ollama" else await telemetria.estima_custo(mdl, ent, sai)
        telemetria.registra(provider=prov, model=mdl, origem=origem,
                            tokens_in=ent, tokens_out=sai, custo_usd=custo,
                            ms=int((time.monotonic() - inicio) * 1000))
        return data

    def _mede_falha(erro: Exception) -> None:
        telemetria.registra(provider="openrouter", model=model or settings.default_model,
                            origem=origem, ms=int((time.monotonic() - inicio) * 1000),
                            ok=False, erro=str(erro)[:200])

    if not key:
        if ollama_ready():
            return await _mede(await _local())
        raise ValueError("Sem chave do OpenRouter (envie no header X-OR-Key ou configure OPENROUTER_API_KEY).")

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Title": settings.site_title,
    }
    try:
        data = await _post_chat(settings.openrouter_base, payload, headers)
    except Exception as e:
        _mede_falha(e)
        if ollama_ready():
            return await _mede(await _local())   # sem internet: o local salva a conversa
        raise
    data["_provider"] = "openrouter"
    return await _mede(data)


async def _stream_once(base: str, payload: dict, headers: dict):
    """Núcleo do streaming: abre a conexão e traduz os pedaços em eventos.

      {"type": "token", "text": "..."}        pedaço de texto
      {"type": "tool_calls", "calls": [...]}  o modelo pediu ferramentas (no fim)
      {"type": "usage", ...}                  contagem real de tokens, quando vier
      {"type": "finish", "reason": "..."}

    Separado de `chat_stream` porque o fallback local usa o MESMO parser: o
    Ollama fala o formato da OpenAI, então não há motivo pra ter dois.

    As chamadas de ferramenta chegam fatiadas (o `arguments` vem letra por
    letra), então acumulamos por índice e só emitimos quando fecha.
    """
    partial: dict[int, dict] = {}   # índice -> chamada de ferramenta em construção
    finish = None

    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        async with client.stream(
            "POST", f"{base}/chat/completions", json=payload, headers=headers,
        ) as resp:
            if resp.status_code >= 400:
                detail = (await resp.aread()).decode("utf-8", "replace")[:400]
                raise httpx.HTTPStatusError(
                    f"{base} respondeu {resp.status_code}: {detail}",
                    request=resp.request, response=resp,
                )
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue

                if chunk.get("usage"):
                    yield {"type": "usage", **chunk["usage"]}

                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    text = delta.get("content")
                    if text:
                        yield {"type": "token", "text": text}
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        slot = partial.setdefault(
                            idx, {"id": None, "function": {"name": "", "arguments": ""}})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["function"]["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["function"]["arguments"] += fn["arguments"]
                    if choice.get("finish_reason"):
                        finish = choice["finish_reason"]

    if partial:
        yield {"type": "tool_calls",
               "calls": [partial[i] for i in sorted(partial)]}
    yield {"type": "finish", "reason": finish or "stop"}


async def chat_stream(messages: list[dict], key: str, model: str | None = None,
                      tools: list | None = None, origem: str = "chat"):
    """Streaming instrumentado. Envelopa `_chat_stream` sem alterar em nada o
    que é emitido — quem consome não percebe diferença.

    Envelope em vez de medir por dentro porque o gerador tem três saídas (sem
    chave, OpenRouter, fallback local) e medir nas três duplicaria a lógica em
    lugares que precisam divergir com o tempo.

    O custo é calculado com `estima_custo_cache` (síncrono) de propósito: este
    bloco roda em `finally`, e `await` ali levanta RuntimeError quando o cliente
    desconecta no meio do streaming. Por isso o preço é aquecido ANTES do laço,
    onde esperar é seguro.
    """
    inicio = time.monotonic()
    prov, mdl = "?", (model or settings.default_model)
    ent = sai = None
    falhou: Exception | None = None

    await telemetria.aquece_precos()

    try:
        async for ev in _chat_stream(messages, key, model, tools):
            tipo = ev.get("type")
            if tipo == "provider":
                prov = ev.get("name", prov)
                mdl = ev.get("model", mdl)
            elif tipo == "usage":
                ent = ev.get("prompt_tokens", ent)
                sai = ev.get("completion_tokens", sai)
            yield ev
    except Exception as e:
        falhou = e
        raise
    finally:
        # Local é de graça de verdade (0.0); cache frio é "não sei" (None).
        custo = 0.0 if prov == "ollama" else telemetria.estima_custo_cache(mdl, ent, sai)
        telemetria.registra(
            provider=prov, model=mdl, origem=origem,
            tokens_in=ent, tokens_out=sai, custo_usd=custo,
            ms=int((time.monotonic() - inicio) * 1000),
            ok=falhou is None, erro=(str(falhou)[:200] if falhou else None),
        )


async def _chat_stream(messages: list[dict], key: str, model: str | None = None,
                       tools: list | None = None):
    """Streaming com o mesmo fallback local do `chat`.

    Emite `{"type":"provider","name":...}` antes do primeiro pedaço, pra o painel
    poder dizer quem respondeu — trocar de modelo sem avisar seria enganoso.

    Um detalhe que importa: se a falha do OpenRouter acontecer DEPOIS de já ter
    emitido texto, não há fallback. Recomeçar no meio duplicaria a resposta na
    tela; nesse caso o erro sobe.
    """
    payload: dict = {
        "model": model or settings.default_model,
        "messages": messages,
        "stream": True,
        # pede a contagem de tokens no último pedaço, pra não estimar custo no cliente
        "stream_options": {"include_usage": True},
    }
    if tools:
        payload["tools"] = tools

    def _payload_local() -> dict:
        return dict(payload, model=settings.ollama_model)

    if not key:
        if not ollama_ready():
            raise ValueError(
                "Sem chave do OpenRouter (envie no header X-OR-Key ou configure OPENROUTER_API_KEY).")
        yield {"type": "provider", "name": "ollama", "model": settings.ollama_model}
        async for ev in _stream_once(settings.ollama_base.rstrip("/"), _payload_local(),
                                     {"Content-Type": "application/json"}):
            yield ev
        return

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Title": settings.site_title,
    }
    emitiu = False
    try:
        async for ev in _stream_once(settings.openrouter_base, payload, headers):
            if not emitiu:
                yield {"type": "provider", "name": "openrouter",
                       "model": payload["model"]}
                emitiu = True
            yield ev
        return
    except Exception:
        if emitiu or not ollama_ready():
            raise

    yield {"type": "provider", "name": "ollama", "model": settings.ollama_model,
           "note": "OpenRouter inacessível; respondendo com o modelo local"}
    async for ev in _stream_once(settings.ollama_base.rstrip("/"), _payload_local(),
                                 {"Content-Type": "application/json"}):
        yield ev


def content_of(data: dict) -> str:
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""
