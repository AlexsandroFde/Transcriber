@echo off
setlocal
cd /d "%~dp0"
echo.
echo === Instalacao do Transcritor de reunioes ===
echo.
where uv >nul 2>nul
if errorlevel 1 (
  echo O gerenciador de pacotes "uv" nao foi encontrado.
  echo Instale-o abrindo o PowerShell e executando:
  echo.
  echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  echo.
  echo Depois feche esta janela e execute instalar.bat novamente.
  pause
  exit /b 1
)
echo Instalando dependencias (a primeira vez baixa cerca de 3 GB, pode demorar)...
uv sync
if errorlevel 1 (
  echo.
  echo Falha na instalacao das dependencias.
  pause
  exit /b 1
)
echo.
echo Verificando o ambiente e baixando os modelos de IA...
uv run transcritor verificar --baixar-modelos
echo.
echo Instalacao concluida. Para transcrever, arraste um video sobre "transcrever.bat".
pause
