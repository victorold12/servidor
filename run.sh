#!/usr/bin/env bash
# VTz LLM Backend — subir localmente (Linux/macOS)
set -e
cd "$(dirname "$0")"

[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env

echo "Backend em http://localhost:8000  (docs em http://localhost:8000/docs)"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
