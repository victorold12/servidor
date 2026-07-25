"""/api/messaging — falar com o JARVIS de dentro do Discord ou Telegram (Seção 5).

O fluxo é: a plataforma chama o webhook → o backend confere que a chamada é
legítima e que quem falou é você → roda o agente → responde de volta na
plataforma.

Duas travas, porque um webhook é uma porta aberta na internet:

  1. Segredo no caminho da URL (o `secret` do path). Sem ele a rota nem existe
     — e o Telegram suporta exatamente isso, `setWebhook` com URL secreta.
  2. Allowlist de quem pode mandar comando (TELEGRAM_ALLOWED_CHATS /
     DISCORD_ALLOWED_USERS). Sem allowlist configurada, a rota RECUSA tudo em
     vez de aceitar tudo: é o JARVIS que mexe no PC do usuário, e o padrão
     seguro é negar.

Nota da Seção 13.3: o PDF rejeita "modelo de aprovação no mesmo canal de chat" —
então este caminho NÃO confirma ação de risco. Comando que exigiria confirmação
continua sendo confirmado na janela nativa do PC, pelo Agente Local. O webhook é
entrada de pedido, não canal de autorização.
"""
import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..config import settings
from ..openrouter import chat, content_of, resolve_key
from ..security import require_token

router = APIRouter()

_MAX = 3500          # Discord corta em 2000, Telegram em 4096; sobra margem


def _lista(valor: str) -> set[str]:
    return {p.strip() for p in (valor or "").split(",") if p.strip()}


def _confere_segredo(secret: str) -> None:
    esperado = settings.messaging_secret
    if not esperado:
        raise HTTPException(
            status_code=503,
            detail="Webhook desabilitado: configure MESSAGING_SECRET pra usar Discord/Telegram.")
    if secret != esperado:
        # 404 e não 403: pra quem varre a internet, a rota simplesmente não existe
        raise HTTPException(status_code=404, detail="Not found")


async def _responde(pergunta: str) -> str:
    key = resolve_key(None)          # webhook não tem header do usuário: usa o do .env
    try:
        data = await chat([{"role": "user", "content": pergunta}], key=key)
        texto = content_of(data).strip()
        return texto[:_MAX] or "(o modelo não respondeu nada)"
    except ValueError:
        return ("Não tenho chave de LLM configurada no servidor — sem OPENROUTER_API_KEY "
                "ou um Ollama local, não consigo responder por aqui.")
    except Exception as exc:  # noqa: BLE001 — a plataforma precisa de uma resposta
        return f"Falhei ao responder: {exc}"


# ----------------------------------------------------------------- Telegram
@router.post("/messaging/telegram/{secret}")
async def telegram(secret: str, request: Request):
    """Webhook do Telegram (configure com setWebhook apontando pra esta URL)."""
    _confere_segredo(secret)
    permitidos = _lista(settings.telegram_allowed_chats)
    if not permitidos:
        raise HTTPException(
            status_code=503,
            detail="Configure TELEGRAM_ALLOWED_CHATS com o seu chat_id antes de usar.")

    corpo = await request.json()
    msg = corpo.get("message") or corpo.get("edited_message") or {}
    chat_id = str((msg.get("chat") or {}).get("id") or "")
    texto = (msg.get("text") or "").strip()

    if not chat_id or not texto:
        return {"ok": True, "ignored": "sem texto"}
    if chat_id not in permitidos:
        # não responde nem explica: quem não está na lista não recebe pista
        return {"ok": True, "ignored": "chat não autorizado"}

    resposta = await _responde(texto)

    if settings.telegram_bot_token:
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
                await client.post(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                    json={"chat_id": chat_id, "text": resposta[:4096]})
        except Exception:  # noqa: BLE001 — falha no envio não derruba o webhook
            return {"ok": True, "sent": False, "answer": resposta}
        return {"ok": True, "sent": True}
    # sem token de bot, devolve no corpo (útil pra testar antes de configurar)
    return {"ok": True, "sent": False, "answer": resposta,
            "note": "configure TELEGRAM_BOT_TOKEN pra eu responder no chat"}


# ------------------------------------------------------------------ Discord
class DiscordIn(BaseModel):
    user_id: str | None = None
    content: str = ""
    channel_id: str | None = None


@router.post("/messaging/discord/{secret}")
async def discord(secret: str, body: DiscordIn):
    """Entrada do Discord.

    Espera um bot/relay simples do lado do Discord repassando {user_id, content}.
    Não implementa a verificação Ed25519 de Interactions da API do Discord — se
    você for ligar isto direto num Application Command, essa checagem precisa
    existir antes, e é melhor eu dizer isso do que fingir que está coberto.
    """
    _confere_segredo(secret)
    permitidos = _lista(settings.discord_allowed_users)
    if not permitidos:
        raise HTTPException(
            status_code=503,
            detail="Configure DISCORD_ALLOWED_USERS com o seu user_id antes de usar.")

    texto = (body.content or "").strip()
    if not texto:
        return {"ok": True, "ignored": "sem texto"}
    if str(body.user_id or "") not in permitidos:
        return {"ok": True, "ignored": "usuário não autorizado"}

    resposta = await _responde(texto)

    if settings.discord_webhook_url:
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
                await client.post(settings.discord_webhook_url,
                                  json={"content": resposta[:2000]})
        except Exception:  # noqa: BLE001
            return {"ok": True, "sent": False, "answer": resposta}
        return {"ok": True, "sent": True}
    return {"ok": True, "sent": False, "answer": resposta,
            "note": "configure DISCORD_WEBHOOK_URL pra eu responder no canal"}


@router.get("/messaging/status", dependencies=[Depends(require_token)])
def status():
    """Diz o que está pronto e o que falta, sem expor segredo nenhum."""
    return {
        "secret_configurado": bool(settings.messaging_secret),
        "telegram": {
            "chats_autorizados": len(_lista(settings.telegram_allowed_chats)),
            "bot_token": bool(settings.telegram_bot_token),
        },
        "discord": {
            "usuarios_autorizados": len(_lista(settings.discord_allowed_users)),
            "webhook": bool(settings.discord_webhook_url),
        },
        "nota": ("Confirmação de ação de risco NÃO passa por aqui (Seção 13.3): "
                 "segue na janela nativa do PC, pelo Agente Local."),
    }
