"""/api/voice — ponte entre a aba de configuração de voz e o Agente Local.

Por que passa pelo backend: o agente é SEMPRE cliente e nunca abre porta
(Seção 8), então o navegador não tem como falar com ele direto. O painel pede
aqui, o backend repassa pelo WebSocket que o agente abriu, e a resposta volta
pelo mesmo caminho.

O que dá pra fazer por aqui (Seção 14):
  - ver o estado real: quais motores estão de pé, o que falta pro STT
  - escolher motor (Chatterbox / Kokoro / navegador) e voz
  - calibrar: exaggeration e cfg_weight do Chatterbox, velocidade do Kokoro
  - subir uma amostra pra clonar a voz, listar e apagar as amostras
  - ouvir um teste com os ajustes atuais antes de salvar

O backend não valida faixa de calibração nem nome de arquivo: quem faz isso é o
agente (voice-config.js), que é o dono da configuração. Validar nos dois lugares
criaria duas verdades — e a que importa é a da máquina onde o áudio toca.
"""
import base64

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .agents_hub import CommandIn, send_command

router = APIRouter()

# Amostra de referência são poucos segundos de áudio. O agente também tem teto
# (8 MB); este aqui é pra recusar antes de carregar na memória do servidor.
_MAX_SAMPLE = 8 * 1024 * 1024


async def _pede(agent_id: str, action: str, args: dict | None = None,
                timeout: float = 60.0):
    """Manda uma ação de voz pro agente e devolve o que ele respondeu."""
    resposta = await send_command(agent_id, CommandIn(
        action=action, args=args or {}, timeout=timeout))
    # o agente responde {ok, data}; erro dele não é erro HTTP nosso
    if isinstance(resposta, dict) and resposta.get("ok") is False:
        return {"ok": False, **(resposta.get("data") or {})}
    return {"ok": True, **((resposta or {}).get("data") or {})}


@router.get("/voice/{agent_id}/status")
async def status(agent_id: str):
    """Estado real da voz naquele PC: motores no ar, config, amostras e STT."""
    return await _pede(agent_id, "voice_status", timeout=20.0)


class ConfigIn(BaseModel):
    engine: str | None = None
    voice: str | None = None
    chatterboxUrl: str | None = None
    kokoroUrl: str | None = None
    exaggeration: float | None = None
    cfg_weight: float | None = None
    temperature: float | None = None
    speed: float | None = None
    language: str | None = None


@router.put("/voice/{agent_id}/config")
async def set_config(agent_id: str, body: ConfigIn):
    """Salva motor, voz e calibração. Campo omitido fica como está."""
    # só o que veio: mandar None faria o agente tratar como "limpar"
    args = {k: v for k, v in body.model_dump().items() if v is not None}
    if not args:
        raise HTTPException(status_code=400, detail="Nada pra mudar.")
    return await _pede(agent_id, "voice_config_set", args)


class SampleIn(BaseModel):
    name: str = "voz.wav"
    data_base64: str


@router.post("/voice/{agent_id}/sample")
async def upload_sample(agent_id: str, body: SampleIn):
    """Sobe um áudio de referência pra clonagem de voz (Chatterbox).

    Recebe base64 em JSON, e não multipart, por dois motivos: o áudio já viaja
    em base64 até o agente pelo WebSocket (então é o mesmo formato de ponta a
    ponta), e multipart exigiria a dependência python-multipart só por causa
    desta rota.

    O arquivo NÃO fica no servidor: é repassado ao agente e vive só no PC do
    usuário. A voz da pessoa é dado biométrico — guardar uma cópia aqui seria
    criar um risco que o produto não precisa ter.
    """
    try:
        bruto = base64.b64decode(body.data_base64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"base64 inválido: {exc}") from exc
    if not bruto:
        raise HTTPException(status_code=400, detail="Áudio vazio.")
    if len(bruto) > _MAX_SAMPLE:
        raise HTTPException(
            status_code=413,
            detail=f"Amostra grande demais ({len(bruto)} bytes; máximo {_MAX_SAMPLE}).")

    return await _pede(agent_id, "voice_save_sample", {
        "name": body.name,
        # reencoda a partir dos bytes validados: garante que o agente recebe
        # base64 canônico, não o que veio do cliente
        "data_base64": base64.b64encode(bruto).decode("ascii"),
    }, timeout=90.0)


@router.get("/voice/{agent_id}/samples")
async def list_samples(agent_id: str):
    return await _pede(agent_id, "voice_list_samples", timeout=20.0)


@router.delete("/voice/{agent_id}/sample/{name}")
async def delete_sample(agent_id: str, name: str):
    return await _pede(agent_id, "voice_delete_sample", {"name": name}, timeout=20.0)


class SpeakIn(BaseModel):
    text: str
    overrides: dict = {}          # testar calibração sem salvar antes


@router.post("/voice/{agent_id}/speak")
async def speak(agent_id: str, body: SpeakIn):
    """Gera a fala. Serve pro botão "testar" da aba de configuração.

    `overrides` permite ouvir uma calibração ANTES de salvar — arrastar o slider,
    ouvir, e só então confirmar.

    O áudio volta em base64 (`audio_base64`), porque atravessa o WebSocket do
    agente. O painel monta um Blob e toca.
    """
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Texto vazio.")
    return await _pede(agent_id, "tts_speak",
                       {"text": body.text, "overrides": body.overrides}, timeout=120.0)


class SttConfigIn(BaseModel):
    binary: str | None = None
    model: str | None = None
    modelsDir: str | None = None
    language: str | None = None
    threads: int | None = None


@router.get("/voice/{agent_id}/stt")
async def get_stt(agent_id: str):
    return await _pede(agent_id, "stt_config_get", timeout=20.0)


@router.put("/voice/{agent_id}/stt")
async def set_stt(agent_id: str, body: SttConfigIn):
    """Troca o modelo do whisper (tiny/base/small/medium/large-v3) e afins.

    A Seção 9 fixa `base` como padrão por causa de RAM; subir pra `large` é
    escolha consciente de trocar memória por precisão.
    """
    args = {k: v for k, v in body.model_dump().items() if v is not None}
    if not args:
        raise HTTPException(status_code=400, detail="Nada pra mudar.")
    return await _pede(agent_id, "stt_config_set", args)
