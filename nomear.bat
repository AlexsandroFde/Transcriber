@echo off
setlocal EnableExtensions
set "PASTA=%~dp0"
set "PYTHONUTF8=1"

if "%~1"=="" (
  echo Arraste o arquivo .json da transcricao sobre este arquivo,
  echo ou informe o caminho abaixo.
  set /p "JSON=Arquivo .json: "
) else (
  set "JSON=%~f1"
)

uv run --project "%PASTA%." transcritor nomear "%JSON:"=%" --interativo
echo.
pause
