"""Guarda as chaves dos conectores em runtime, setadas pelo próprio site.

Grava num arquivo local (runtime_config.json, fora do git). Cada chave: usa o
valor setado pelo site; se vazio, cai no .env. Assim o usuário configura tudo
pela interface, sem editar arquivo.

Aviso: as chaves ficam em texto neste arquivo, no servidor. Ok pra uso local
single-user. Num backend público, proteja com autenticação (ver README).
"""
import json
from pathlib import Path

from .config import settings

_FILE = Path(__file__).resolve().parent.parent / "runtime_config.json"
_data: dict = {}

_ENV_FALLBACK = {
    "notion_token": lambda: settings.notion_token,
    "figma_token": lambda: settings.figma_token,
    "google_client_id": lambda: settings.google_client_id,
    "google_client_secret": lambda: settings.google_client_secret,
    "google_redirect_uri": lambda: settings.google_redirect_uri,
}


def _load():
    global _data
    if _FILE.exists():
        try:
            _data = json.loads(_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _data = {}


_load()


def get_secret(name: str) -> str:
    val = _data.get(name)
    if val:
        return val
    fb = _ENV_FALLBACK.get(name)
    return fb() if fb else ""


def set_secrets(updates: dict):
    """Atualiza as chaves. Valor "" limpa; chave ausente/None fica como está."""
    for key, val in updates.items():
        if val is None or key not in _ENV_FALLBACK:
            continue
        if val == "":
            _data.pop(key, None)
        else:
            _data[key] = val
    _FILE.write_text(json.dumps(_data, indent=2), encoding="utf-8")


def status() -> dict:
    """Quais estão configuradas (sem revelar o valor)."""
    return {k: bool(get_secret(k)) for k in _ENV_FALLBACK if k != "google_redirect_uri"}
