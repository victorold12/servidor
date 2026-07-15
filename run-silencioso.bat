@echo off
REM Versao silenciosa (sem pause) usada pelo iniciar-invisivel.vbs.
REM Assume que o run.bat ja foi rodado uma vez (venv + deps prontos).
cd /d "%~dp0"
if not exist ".venv" (
  REM ainda nao configurado: cai pro run.bat normal (com janela) pra instalar
  start "" "%~dp0run.bat"
  exit /b 0
)
call .venv\Scripts\activate.bat
uvicorn app.main:app --host 0.0.0.0 --port 8000
