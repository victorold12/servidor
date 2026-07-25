"""Teste da ponte de voz (/api/voice/...) entre o painel e o Agente Local.

Roda sem pytest:  python3 tests/test_voice_routes.py

Sem WebSocket real: `send_command` é substituído, registrando qual ação e quais
args chegariam no agente.

O que importa aqui:
  - a ação certa é despachada com os args certos
  - campo omitido não vira None no agente (senão "não mexi nisso" viraria "limpa")
  - amostra de voz: base64 inválido e tamanho excessivo são recusados ANTES de
    ocupar a memória do servidor
  - o áudio de referência não é gravado no servidor (é dado biométrico)
  - `overrides` no /speak permite testar calibração sem salvar
  - erro do agente (ok:false) não vira 500: é repassado com o motivo
  - as rotas exigem token de sessão
"""
import base64
import json
import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

import app.db as db  # noqa: E402

db._DB_PATH = Path(tempfile.mkdtemp()) / "test-voice.db"
os.environ["BACKEND_TOKEN"] = "seg"
import app.config as config  # noqa: E402

config.settings.backend_token = "seg"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app import security as sec_mod  # noqa: E402
from app.routers import voice as voice_mod  # noqa: E402

db.init_db()

SESSION = {"X-Backend-Token": "seg"}
_fails = 0
_ultima = {}


def check(cond, label):
    global _fails
    print(("  ok  " if cond else " FAIL ") + label)
    if not cond:
        _fails += 1


def zera():
    sec_mod._hits.clear()
    _ultima.clear()


def stub_agente(resposta=None, ok=True):
    """Substitui o despacho pro agente e guarda o que foi pedido."""
    async def fake_send(agent_id, body):
        _ultima["agent_id"] = agent_id
        _ultima["action"] = body.action
        _ultima["args"] = body.args
        _ultima["timeout"] = body.timeout
        return {"ok": ok, "data": resposta if resposta is not None else {"feito": True}}
    voice_mod.send_command = fake_send


client = TestClient(app)


def test_status():
    print("\n1. status pede voice_status e repassa o estado real")
    zera()
    stub_agente({
        "engines": {"chatterbox": {"up": False, "reason": "não está rodando"},
                    "kokoro": {"up": True}},
        "config": {"engine": "chatterbox", "exaggeration": 0.5},
        "samples": [{"name": "minha-voz.wav", "size": 120000}],
        "stt": {"model": "base", "model_present": False, "hint": "baixe ggml-base.bin"},
        "ranges": {"exaggeration": {"min": 0.25, "max": 2.0}},
    })
    j = client.get("/api/voice/ag-1/status", headers=SESSION).json()
    check(_ultima["action"] == "voice_status", "despacha voice_status")
    check(_ultima["agent_id"] == "ag-1", "pro agente pedido")
    check(j["engines"]["chatterbox"]["up"] is False, "repassa que o Chatterbox não está de pé")
    check(j["engines"]["kokoro"]["up"] is True, "e que o Kokoro está")
    check(j["stt"]["hint"].startswith("baixe"), "repassa o que falta pro STT")
    check(j["ranges"]["exaggeration"]["max"] == 2.0, "manda as faixas pros sliders")


def test_config_so_manda_o_que_veio():
    print("\n2. campo omitido NÃO vira None no agente")
    zera()
    stub_agente({"config": {"engine": "kokoro"}})
    client.put("/api/voice/ag-1/config", headers=SESSION, json={"engine": "kokoro"})
    check(_ultima["action"] == "voice_config_set", "despacha voice_config_set")
    check(_ultima["args"] == {"engine": "kokoro"},
          f"só o campo enviado (veio {_ultima['args']})")
    check("voice" not in _ultima["args"], "não manda voice=None (seria 'limpa a voz')")
    check("exaggeration" not in _ultima["args"], "nem calibração que não foi mexida")

    zera()
    stub_agente()
    r = client.put("/api/voice/ag-1/config", headers=SESSION, json={})
    check(r.status_code == 400, "corpo vazio é recusado em vez de despachar nada")


def test_config_calibracao():
    print("\n3. calibração completa chega ao agente")
    zera()
    stub_agente({"config": {}})
    client.put("/api/voice/ag-1/config", headers=SESSION, json={
        "engine": "chatterbox", "voice": "minha-voz.wav",
        "exaggeration": 0.9, "cfg_weight": 0.3, "temperature": 0.7})
    a = _ultima["args"]
    check(a["exaggeration"] == 0.9 and a["cfg_weight"] == 0.3,
          "exaggeration e cfg_weight passam")
    check(a["voice"] == "minha-voz.wav", "a voz escolhida passa")


def test_amostra():
    print("\n4. subir amostra de voz")
    zera()
    stub_agente({"saved": {"name": "minha-voz.wav", "size": 18}})
    audio = b"RIFF" + b"\x00" * 14
    r = client.post("/api/voice/ag-1/sample", headers=SESSION, json={
        "name": "minha-voz.wav", "data_base64": base64.b64encode(audio).decode()})
    check(r.status_code == 200, "aceita o áudio")
    check(_ultima["action"] == "voice_save_sample", "despacha voice_save_sample")
    check(base64.b64decode(_ultima["args"]["data_base64"]) == audio,
          "o agente recebe os bytes exatos")
    check(_ultima["timeout"] >= 60, "timeout folgado (arquivo leva mais que um comando)")


def test_amostra_recusas():
    print("\n5. amostra inválida é recusada antes de ir pro agente")
    zera()
    stub_agente()
    ruim = client.post("/api/voice/ag-1/sample", headers=SESSION,
                       json={"data_base64": "não é base64!!!"})
    check(ruim.status_code == 400, f"base64 inválido = 400 (veio {ruim.status_code})")
    check("action" not in _ultima, "e nada foi despachado pro agente")

    zera()
    stub_agente()
    vazio = client.post("/api/voice/ag-1/sample", headers=SESSION, json={"data_base64": ""})
    check(vazio.status_code == 400, "áudio vazio = 400")

    zera()
    stub_agente()
    grande = base64.b64encode(b"\x00" * (9 * 1024 * 1024)).decode()
    r = client.post("/api/voice/ag-1/sample", headers=SESSION, json={"data_base64": grande})
    check(r.status_code == 413, f"grande demais = 413 (veio {r.status_code})")
    check("action" not in _ultima, "recusado sem ocupar o agente")


def test_amostra_nao_fica_no_servidor():
    print("\n6. o áudio de referência não é gravado no servidor (é biométrico)")
    zera()
    stub_agente({"saved": {"name": "v.wav"}})
    marca = b"RIFF-MARCA-UNICA-DE-VOZ-" + os.urandom(8)
    client.post("/api/voice/ag-1/sample", headers=SESSION, json={
        "name": "v.wav", "data_base64": base64.b64encode(marca).decode()})

    achados = []
    for raiz, _dirs, arquivos in os.walk(_REPO):
        if "/.git" in raiz or "__pycache__" in raiz:
            continue
        for nome in arquivos:
            caminho = os.path.join(raiz, nome)
            try:
                if os.path.getsize(caminho) < 4_000_000 and marca in open(caminho, "rb").read():
                    achados.append(caminho)
            except OSError:
                pass
    check(not achados, f"nenhum arquivo do servidor contém o áudio (achados: {achados})")


def test_speak_overrides():
    print("\n7. /speak permite ouvir a calibração ANTES de salvar")
    zera()
    stub_agente({"engine": "chatterbox", "fallback": False,
                 "audio_base64": base64.b64encode(b"RIFFaudio").decode(), "mime": "audio/wav"})
    r = client.post("/api/voice/ag-1/speak", headers=SESSION, json={
        "text": "olá senhor", "overrides": {"exaggeration": 1.5}})
    j = r.json()
    check(_ultima["action"] == "tts_speak", "despacha tts_speak")
    check(_ultima["args"]["overrides"]["exaggeration"] == 1.5,
          "os overrides chegam (testar sem salvar)")
    check(base64.b64decode(j["audio_base64"]) == b"RIFFaudio", "o áudio volta ao painel")
    check(j["mime"] == "audio/wav", "com o tipo")

    zera()
    stub_agente()
    vazio = client.post("/api/voice/ag-1/speak", headers=SESSION, json={"text": "  "})
    check(vazio.status_code == 400, "texto vazio é recusado")


def test_erro_do_agente():
    print("\n8. erro do agente é repassado com o motivo, não vira 500")
    zera()
    stub_agente({"reason": "nenhum motor de TTS local respondeu",
                 "hint": "suba o Chatterbox-TTS-Server"}, ok=False)
    r = client.post("/api/voice/ag-1/speak", headers=SESSION, json={"text": "oi"})
    j = r.json()
    check(r.status_code == 200, f"não é erro HTTP nosso (veio {r.status_code})")
    check(j["ok"] is False, "mas ok:false")
    check("nenhum motor" in j["reason"], "com o motivo do agente")
    check("Chatterbox" in j["hint"], "e a dica")


def test_stt():
    print("\n9. trocar o modelo do whisper")
    zera()
    stub_agente({"config": {"model": "small"}})
    client.put("/api/voice/ag-1/stt", headers=SESSION, json={"model": "small", "threads": 6})
    check(_ultima["action"] == "stt_config_set", "despacha stt_config_set")
    check(_ultima["args"] == {"model": "small", "threads": 6}, "só o que veio")

    zera()
    stub_agente({"config": {"model": "base"}, "setup": {"model_present": False}})
    j = client.get("/api/voice/ag-1/stt", headers=SESSION).json()
    check(_ultima["action"] == "stt_config_get", "leitura também")
    check(j["setup"]["model_present"] is False, "diz se o modelo está baixado")


def test_samples_crud():
    print("\n10. listar e apagar amostras")
    zera()
    stub_agente({"samples": [{"name": "a.wav"}, {"name": "b.wav"}]})
    j = client.get("/api/voice/ag-1/samples", headers=SESSION).json()
    check(len(j["samples"]) == 2, "lista as amostras")

    zera()
    stub_agente({"deleted": True})
    client.delete("/api/voice/ag-1/sample/a.wav", headers=SESSION)
    check(_ultima["action"] == "voice_delete_sample", "despacha a remoção")
    check(_ultima["args"]["name"] == "a.wav", "com o nome")


def test_exige_token():
    print("\n11. as rotas de voz exigem token de sessão")
    zera()
    stub_agente()
    for metodo, url in [("get", "/api/voice/ag-1/status"),
                        ("get", "/api/voice/ag-1/samples"),
                        ("get", "/api/voice/ag-1/stt")]:
        r = getattr(client, metodo)(url)
        check(r.status_code in (401, 403), f"{url} sem token não passa ({r.status_code})")
    r = client.post("/api/voice/ag-1/speak", json={"text": "oi"})
    check(r.status_code in (401, 403), "speak sem token não passa")


for fn in [test_status, test_config_so_manda_o_que_veio, test_config_calibracao,
           test_amostra, test_amostra_recusas, test_amostra_nao_fica_no_servidor,
           test_speak_overrides, test_erro_do_agente, test_stt,
           test_samples_crud, test_exige_token]:
    fn()

print("\n" + ("TODOS OS TESTES PASSARAM" if not _fails else f"{_fails} FALHA(S)"))
sys.exit(1 if _fails else 0)
