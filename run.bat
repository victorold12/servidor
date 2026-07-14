@echo off
REM ============================================================
REM  VTz LLM Backend - subir localmente (Windows)
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist ".venv" (
  echo Criando ambiente virtual...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

echo Instalando dependencias...
pip install -q -r requirements.txt

if not exist ".env" (
  copy .env.example .env >nul
  echo .env criado a partir do exemplo. Preencha as chaves se precisar.
)

echo.
echo Backend em http://localhost:8000  (docs em http://localhost:8000/docs)
echo Ctrl+C para parar.
echo.
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
endlocal
