@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "PASTA=%~dp0"
set "PYTHONUTF8=1"
set "ARQUIVO="
set "SAIDA="

if "%~1"=="" (
  echo Arraste um ou mais videos sobre este arquivo, ou informe o caminho abaixo.
  set /p "ARQUIVO=Arquivo de video ou audio: "
)
if defined ARQUIVO (
  set "ARQUIVO=!ARQUIVO:"=!"
  for %%I in ("!ARQUIVO!") do (
    set "ARQUIVO=%%~fI"
    set "SAIDA=%%~dpI%%~nI_transcricao"
  )
) else (
  if "%~2"=="" set "SAIDA=%~dp1%~n1_transcricao"
)

echo.
set "NPART="
set /p "NPART=Numero de participantes (Enter se nao souber): "
set "CONTEXTO="
set /p "CONTEXTO=Assunto da reuniao, opcional (Enter para pular): "

set "EXTRA="
if not "!NPART!"=="" set "EXTRA=-n !NPART!"
if exist "%PASTA%glossario.txt" (
  echo Usando o glossario: %PASTA%glossario.txt
  set "EXTRA=!EXTRA! -g "%PASTA%glossario.txt""
)

if defined ARQUIVO (
  uv run --project "%PASTA%." transcritor transcrever "!ARQUIVO!" !EXTRA! -c "!CONTEXTO!"
) else (
  uv run --project "%PASTA%." transcritor transcrever %* !EXTRA! -c "!CONTEXTO!"
)
set "CODIGO=!ERRORLEVEL!"

echo.
if "!CODIGO!"=="0" (
  echo Transcricao concluida.
  if defined SAIDA if exist "!SAIDA!" explorer "!SAIDA!"
) else (
  echo Houve erro no processamento. Veja as mensagens acima e o arquivo .log na pasta de saida.
)
pause
