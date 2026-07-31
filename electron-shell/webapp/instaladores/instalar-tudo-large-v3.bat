@echo off
chcp 65001 >nul
setlocal EnableExtensions
title JARVIS - baixar e organizar tudo
cd /d "%~dp0"

REM ============ onde tudo vai morar ============
REM Uma raiz só, com as coisas separadas por assunto. Apagar esta pasta
REM desinstala tudo que este script trouxe — nada vai parar no Windows,
REM em Arquivos de Programas, nem no registro.
set "RAIZ="
for /f "usebackq tokens=2,*" %%A in (`reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders" /v Personal 2^>nul`) do set "DOCS=%%B"
if not defined DOCS set "DOCS=%USERPROFILE%\Documents"
set "RAIZ=%DOCS%\VTz LLM"
set "VOZES=%RAIZ%\vozes"
set "WPROG=%RAIZ%\whisper\programa"
set "WMOD=%RAIZ%\whisper\modelos"
set "FALHOU="

echo.
echo ===============================================
echo  JARVIS - baixar e organizar as dependencias
echo ===============================================
echo.
echo  Vai criar esta arvore:
echo.
echo     Documentos\VTz LLM\
echo       vozes\Chatterbox-TTS-Server\      voz clonada
echo       vozes\Kokoro-FastAPI\      vozes prontas
echo       whisper\programa\               transcricao
echo       whisper\modelos\                modelo large-v3
echo       LEIA-ME.txt                      como ligar cada coisa
echo       resumo-da-instalacao.txt         o que entrou e o que nao
echo.
echo  Sao varios GB. Cada etapa pula sozinha se ja estiver feita,
echo  entao rodar de novo e seguro - e e assim que se conserta uma
echo  etapa que falhou.
echo.
echo  Instalado em: %RAIZ%
echo  Desinstalar = apagar essa pasta.
echo.
call :pausa
echo.

if not exist "%VOZES%" mkdir "%VOZES%"
if not exist "%WPROG%" mkdir "%WPROG%"
if not exist "%WMOD%"  mkdir "%WMOD%"

REM ============ 1. winget ============
where winget >nul 2>nul
if errorlevel 1 (
  echo [ATENCAO] winget nao encontrado. Ele vem no "Instalador de Aplicativo"
  echo           da Microsoft Store. Sem ele eu nao instalo Git/Python/ffmpeg
  echo           sozinho; o resto segue e no fim eu digo o que faltou.
  set "SEMWINGET=1"
  echo.
)

REM ============ 2. Git ============
echo --- [1/7] Git
call :garante "git --version" Git.Git Git https://git-scm.com
echo.

REM ============ 3. Python 3.12 ============
REM 3.12 por causa do Chatterbox: ele fixa torch==2.5.1, que nao tem
REM instalador pra Python 3.13+. Conviver com um Python mais novo no
REM mesmo PC nao da problema - o lancador `py` escolhe qual usar.
echo --- [2/7] Python 3.12
call :garante "py -3.12 --version" Python.Python.3.12 Python3.12 https://www.python.org/downloads/
echo.

REM ============ 4. ffmpeg ============
echo --- [3/7] ffmpeg
call :garante "ffmpeg -version" Gyan.FFmpeg ffmpeg https://ffmpeg.org
echo.

REM ============ 5. modelo do whisper ============
echo --- [4/7] Modelo do whisper (large-v3)
set "WBIN=%WMOD%\ggml-large-v3.bin"
if exist "%WBIN%" (
  echo      [ok] ja baixado.
) else (
  echo      baixando; e grande, pode demorar bastante.
  curl -L --fail --progress-bar -o "%WBIN%" "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin" || (
    echo      [ERRO] download falhou.
    del /q "%WBIN%" 2>nul
    set "FALHOU=%FALHOU% modelo-whisper"
  )
)
if exist "%WBIN%" (
  for /f "usebackq" %%A in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "[int]((Get-Item '%WBIN%').Length/1MB)"`) do set "WMB=%%A"
  call :confere_tamanho
)
echo.

REM ============ 6. programa do whisper.cpp ============
REM NAO chuto o nome do arquivo: ele muda a cada release. Pergunto ao
REM GitHub qual e o anexo de Windows da versao mais nova, na hora. Assim
REM o script continua valendo depois que o projeto publicar outra versao.
echo --- [5/7] Programa do whisper.cpp
if exist "%WPROG%\whisper-cli.exe" (
  echo      [ok] ja esta aqui.
) else (
  echo      procurando a versao mais nova...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; try{ $r=Invoke-RestMethod -Uri 'https://api.github.com/repos/ggml-org/whisper.cpp/releases/latest' -Headers @{'User-Agent'='jarvis'}; $zips=$r.assets | Where-Object { $_.name -like '*.zip' }; $a=$zips | Where-Object { $_.name -match 'win' -and $_.name -match 'x64' } | Select-Object -First 1; if(-not $a){ $a=$zips | Where-Object { $_.name -match 'win|x64|bin' } | Select-Object -First 1 } if(-not $a){ throw ('nenhum anexo servivel. Anexos desta release: ' + (($r.assets | ForEach-Object { $_.name }) -join ', ')) } Write-Host ('      achei: ' + $a.name); $z=Join-Path $env:TEMP $a.name; Invoke-WebRequest -Uri $a.browser_download_url -OutFile $z; Expand-Archive -Path $z -DestinationPath '%WPROG%' -Force; Remove-Item $z -Force; $exe=Get-ChildItem -Path '%WPROG%' -Recurse -Filter 'whisper-cli.exe' | Select-Object -First 1; if(-not $exe){ $exe=Get-ChildItem -Path '%WPROG%' -Recurse -Filter 'main.exe' | Select-Object -First 1 } if(-not $exe){ throw 'baixou e extraiu, mas nao achei whisper-cli.exe nem main.exe dentro' } if($exe.FullName -ne (Join-Path '%WPROG%' 'whisper-cli.exe')){ Copy-Item $exe.FullName (Join-Path '%WPROG%' 'whisper-cli.exe') -Force } Write-Host '      [ok] instalado.'; exit 0 }catch{ Write-Host ('      [ERRO] ' + $_.Exception.Message); exit 1 }"
  if errorlevel 1 (
    echo      Pegue o zip de Windows a mao em:
    echo          https://github.com/ggml-org/whisper.cpp/releases
    echo      e ponha whisper-cli.exe em: %WPROG%
    set "FALHOU=%FALHOU% whisper-cli"
  )
)
echo.

REM ============ 7. Chatterbox e Kokoro ============
echo --- [6/7] Chatterbox (clona a sua voz)
if defined JARVIS_PULAR_VOZES (
  echo      [pulado] JARVIS_PULAR_VOZES ligado.
) else (
  call :instala_python_repo "https://github.com/devnen/Chatterbox-TTS-Server" "Chatterbox-TTS-Server" 1 chatterbox chatterbox-tts sim sim
)
echo.
echo --- [7/7] Kokoro (vozes prontas)
if defined JARVIS_PULAR_VOZES (
  echo      [pulado] JARVIS_PULAR_VOZES ligado.
) else (
  call :instala_python_repo "https://github.com/remsky/Kokoro-FastAPI" "Kokoro-FastAPI" 2
)
echo.

REM ============ apontar o Agente Local pras pastas novas ============
REM Sem isto o agente procuraria o modelo em ~/.jarvis-agente/whisper-models
REM e nao acharia nada - a organizacao em pastas viraria justamente o
REM motivo de nao funcionar. Mescla no stt.json que ja existe, em vez de
REM sobrescrever: as escolhas de modelo e threads sao preservadas.
echo --- Apontando o Agente Local pras pastas
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; try{ $d=Join-Path $env:USERPROFILE '.jarvis-agente'; if(-not (Test-Path $d)){ New-Item -ItemType Directory -Path $d | Out-Null } $f=Join-Path $d 'stt.json'; $c=@{}; if(Test-Path $f){ $c=Get-Content $f -Raw | ConvertFrom-Json -AsHashtable } $c['modelsDir']='%WMOD%'; $exe=Join-Path '%WPROG%' 'whisper-cli.exe'; if(Test-Path $exe){ $c['binary']=$exe } $c['model']='large-v3'; $c | ConvertTo-Json -Depth 5 | Set-Content $f -Encoding UTF8; Write-Host '      [ok] stt.json atualizado.' }catch{ Write-Host ('      [aviso] nao consegui escrever stt.json: ' + $_.Exception.Message) }"
echo.

REM ============ papeis que ficam na pasta ============
echo --- Atalhos pra ligar as vozes
> "%RAIZ%\ligar-vozes.bat" (
  echo @echo off
  echo title Ligando as vozes do JARVIS
  echo cd /d "%%~dp0"
  echo if exist "vozes\Chatterbox-TTS-Server\.venv\Scripts\activate.bat" (
  echo   start "Chatterbox ^(porta 8004^)" cmd /k "cd /d vozes\Chatterbox-TTS-Server ^&^& call .venv\Scripts\activate.bat ^&^& python server.py"
  echo ^) else ^( echo [pulado] Chatterbox nao instalado. ^)
  echo if exist "vozes\Kokoro-FastAPI\.venv\Scripts\activate.bat" (
  echo   start "Kokoro ^(porta 8880^)" cmd /k "cd /d vozes\Kokoro-FastAPI ^&^& call .venv\Scripts\activate.bat ^&^& python server.py"
  echo ^) else ^( echo [pulado] Kokoro nao instalado. ^)
  echo echo.
  echo echo Os dois servidores estao subindo em janelas minimizadas.
  echo echo Na PRIMEIRA vez o Chatterbox baixa ~2 GB e demora - deixe terminar.
  echo echo Abra o JARVIS: Configuracoes ^^^> Voz.
  echo timeout /t 6 ^>nul
)
echo      [ok] ligar-vozes.bat criado.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; try{ $ini=[Environment]::GetFolderPath('Startup'); $lnk=Join-Path $ini 'JARVIS - vozes.lnk'; $w=New-Object -ComObject WScript.Shell; $a=$w.CreateShortcut($lnk); $a.TargetPath='%RAIZ%\ligar-vozes.bat'; $a.WorkingDirectory='%RAIZ%'; $a.WindowStyle=7; $a.Description='Sobe Chatterbox e Kokoro para o JARVIS'; $a.Save(); Write-Host '      [ok] vao ligar sozinhos quando voce entrar no Windows.'; Write-Host ('      Pra desligar isso, apague: ' + $lnk) }catch{ Write-Host ('      [aviso] nao consegui criar o atalho de inicializacao: ' + $_.Exception.Message) }"
echo.

> "%RAIZ%\LEIA-ME.txt" (
  echo JARVIS - dependencias instaladas aqui
  echo =====================================
  echo.
  echo vozes\Chatterbox-TTS-Server
  echo     Clona a SUA voz. Para ligar:
  echo         cd vozes\Chatterbox-TTS-Server
  echo         .venv\Scripts\activate.bat
  echo         python server.py
  echo     O JARVIS procura na porta 8004.
  echo.
  echo vozes\Kokoro-FastAPI
  echo     Vozes prontas, mais leve. Mesmos passos, porta 8880.
  echo     E o reserva: entra sozinho se o Chatterbox nao estiver de pe.
  echo.
  echo whisper\programa   - whisper-cli.exe, transcreve o que voce fala
  echo whisper\modelos    - ggml-large-v3.bin
  echo     O Agente Local ja foi apontado pra ca ^(stt.json^).
  echo.
  echo Desinstalar tudo: apagar a pasta JARVIS.
  echo Git, Python e ffmpeg foram instalados pelo winget e ficam fora
  echo daqui - remova por "Adicionar ou remover programas" se quiser.
)

> "%RAIZ%\resumo-da-instalacao.txt" (
  echo Instalacao rodada em %DATE% %TIME%
  if defined FALHOU ( echo Ficou faltando:%FALHOU% ) else ( echo Tudo entrou. )
)

echo ===============================================
if defined FALHOU (
  echo  Terminou, mas ficou faltando:%FALHOU%
  echo  O resto esta instalado e funciona. Resolva o que falta e rode
  echo  este arquivo de novo - ele pula tudo que ja deu certo.
) else (
  echo  Tudo instalado e organizado.
)
echo ===============================================
echo.
echo  Pasta: %RAIZ%
echo  Leia o LEIA-ME.txt de la pra saber como ligar cada coisa.
echo.
echo  No app: Configuracoes ^> Voz ^> escolha o motor ^> Salvar.
echo.
call :pausa
exit /b 0

REM ---------- sub-rotinas ----------
:pausa
if defined JARVIS_SEM_PAUSA exit /b 0
pause
exit /b 0

:garante
setlocal
set "TESTE=%~1"
set "WID=%~2"
set "NOME=%~3"
set "SITE=%~4"
%TESTE% >nul 2>nul
if not errorlevel 1 ( echo      [ok] ja instalado. & endlocal & exit /b 0 )
if defined SEMWINGET (
  echo      [FALTA] %NOME%. Instale em %SITE% e rode este arquivo de novo.
  endlocal & set "FALHOU=%FALHOU% %~3" & exit /b 0
)
echo      instalando pelo winget...
winget install --id %WID% -e --accept-source-agreements --accept-package-agreements
call :recarrega_path
%TESTE% >nul 2>nul
if not errorlevel 1 ( echo      [ok] instalado. & endlocal & exit /b 0 )
echo      [ATENCAO] instalou, mas este terminal ainda nao enxerga %NOME%.
echo                Isso e normal: o Windows so entrega o PATH novo pra
echo                janelas abertas DEPOIS da instalacao. FECHE esta janela
echo                e rode este arquivo de novo - ele pula o que ja entrou.
endlocal & set "FALHOU=%FALHOU% %~3" & exit /b 0

:recarrega_path
for /f "usebackq tokens=2,*" %%A in (`reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul`) do set "PATH_M=%%B"
for /f "usebackq tokens=2,*" %%A in (`reg query "HKCU\Environment" /v Path 2^>nul`) do set "PATH_U=%%B"
if defined PATH_M set "PATH=%PATH_M%"
if defined PATH_U set "PATH=%PATH%;%PATH_U%"
exit /b 0

:confere_tamanho
if not defined WMB ( echo      [aviso] nao consegui medir o arquivo; seguindo. & exit /b 0 )
if %WMB% LSS 2500 (
  echo      [ERRO] veio so %WMB% MB; o modelo large-v3 tem uns 2500 MB ou mais.
  echo             Provavelmente baixou uma pagina de erro no lugar do modelo.
  del /q "%WBIN%" 2>nul
  set "FALHOU=%FALHOU% modelo-whisper"
) else ( echo      [ok] %WMB% MB. )
exit /b 0

:instala_python_repo
setlocal
set "REPO=%~1"
set "PASTA=%VOZES%\%~2"
set "PRECISA312=%~3"
set "MODULO=%~4"
set "PACOTE=%~5"
set "ALINHA_TORCH=%~6"
set "DESLIGA_MARCA=%~7"
set "PY=python"
if not "%PRECISA312%"=="0" ( py -3.12 --version >nul 2>nul && set "PY=py -3.12" )
if "%PRECISA312%"=="1" if "%PY%"=="python" (
  echo      [pulado] precisa do Python 3.12, que nao esta disponivel.
  endlocal & set "FALHOU=%FALHOU% %~2" & exit /b 0
)
where git >nul 2>nul || (
  echo      [pulado] precisa do Git.
  endlocal & set "FALHOU=%FALHOU% %~2" & exit /b 0
)
if exist "%PASTA%" (
  echo      atualizando...
  pushd "%PASTA%" & git pull >nul 2>nul & popd
) else (
  echo      clonando %REPO% ...
  git clone --depth 1 "%REPO%" "%PASTA%" || (
    echo      [ERRO] nao consegui clonar.
    endlocal & set "FALHOU=%FALHOU% %~2" & exit /b 0
  )
)
pushd "%PASTA%"
if exist ".venv" (
  call ".venv\Scripts\activate.bat"
  if "%PRECISA312%"=="1" (
    python -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) else 1)" >nul 2>nul
    if errorlevel 1 (
      echo      [refazendo] ambiente criado com Python incompativel.
      call deactivate >nul 2>nul
      rmdir /s /q ".venv"
    )
  )
)
if not exist ".venv" %PY% -m venv .venv
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip >nul
if not exist "requirements.txt" (
  echo      [ATENCAO] sem requirements.txt; veja o README de %REPO%.
  popd & endlocal & set "FALHOU=%FALHOU% %~2" & exit /b 0
)
pip install -r requirements.txt || (
  echo      [ERRO] instalacao das dependencias falhou.
  echo             "Could not find a version ... torch" = Python incompativel.
  echo             erro de compilador ou CUDA = placa de video.
  popd & endlocal & set "FALHOU=%FALHOU% %~2" & exit /b 0
)
if defined MODULO (
  python -c "import %MODULO%" >nul 2>nul
  if errorlevel 1 (
    echo      faltou o motor ^(%MODULO%^); instalando %PACOTE%...
    pip install %PACOTE% || (
      echo      [ERRO] nao consegui instalar %PACOTE%.
      popd ^& endlocal ^& set "FALHOU=%FALHOU% %~2" ^& exit /b 0
    )
  )
)
if defined ALINHA_TORCH (
  echo      alinhando torch/torchvision/torchaudio ^(2.6.0^)...
  pip install torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0
)
if defined DESLIGA_MARCA if exist "config.yaml" (
  echo      desligando a marca-d^'agua ^(perth^)...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "try{ $f='config.yaml'; $t=Get-Content $f -Raw; $n=[regex]::Replace($t,'(?im)^(\s*enable_watermarking\s*:\s*)true\s*$','${1}false'); if($n -ne $t){ Set-Content $f $n -Encoding UTF8; Write-Host '      [ok] marca-d''agua desligada.' } else { Write-Host '      (nada pra desligar no config.yaml)' } }catch{ Write-Host ('      [aviso] nao consegui editar config.yaml: ' + $_.Exception.Message) }"
)
echo      [ok] pronto em %PASTA%
popd
endlocal & exit /b 0
