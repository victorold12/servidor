@echo off
REM ============================================================
REM  VTz LLM Backend - subir localmente (Windows)
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo === VTz LLM Backend ===
echo.

REM 1) Acha o Python (python ou o launcher py)
set PYCMD=
where python >nul 2>nul
if not errorlevel 1 set PYCMD=python
if not defined PYCMD (
  where py >nul 2>nul
  if not errorlevel 1 set PYCMD=py
)
if not defined PYCMD (
  echo [ERRO] Python nao encontrado no PATH.
  echo Instale em https://python.org/downloads
  echo IMPORTANTE: marque "Add python.exe to PATH" durante a instalacao.
  echo Depois feche esta janela e rode o run.bat de novo.
  echo.
  pause
  exit /b 1
)
echo Python encontrado: %PYCMD%

REM 2) Cria o ambiente virtual se nao existir
if not exist ".venv" (
  echo Criando ambiente virtual...
  %PYCMD% -m venv .venv
  if errorlevel 1 (
    echo [ERRO] Falha ao criar o ambiente virtual.
    pause
    exit /b 1
  )
)

REM 3) Ativa o ambiente virtual
call .venv\Scripts\activate.bat
if errorlevel 1 (
  echo [ERRO] Falha ao ativar o ambiente virtual. Apague a pasta .venv e rode de novo.
  pause
  exit /b 1
)

REM 4) Instala as dependencias
echo Instalando dependencias (pode demorar na primeira vez)...
pip install -q -r requirements.txt
if errorlevel 1 (
  echo [ERRO] Falha ao instalar dependencias. Veja a mensagem acima.
  pause
  exit /b 1
)

REM 5) Cria o .env se nao existir
if not exist ".env" (
  copy .env.example .env >nul
  echo .env criado a partir do exemplo. Preencha as chaves se precisar.
)

echo.
echo Backend em http://localhost:8000  (docs em http://localhost:8000/docs)
echo Ctrl+C para parar.
echo.
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
if errorlevel 1 (
  echo.
  echo [ERRO] O servidor parou com erro. Veja a mensagem acima.
)

echo.
echo Servidor encerrado.
pause
endlocal
