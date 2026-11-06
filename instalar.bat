@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Instalacao do Transcritor
echo.
echo   Instalacao do Transcritor de reunioes
echo   So e preciso fazer isto uma vez, e de novo depois de atualizar o programa.
echo.

if exist "%LOCALAPPDATA%\transcritor\instancia.json" (
  echo   O Transcritor parece estar aberto. Feche-o antes de continuar.
  pause
)

set "UV="
where uv >nul 2>nul && set "UV=uv"
if not defined UV if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
if defined UV echo   [1/4] Gerenciador de pacotes uv: ja instalado.
if not defined UV (
  echo   [1/4] Instalando o gerenciador de pacotes uv...
  powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
)
if not defined UV (
  echo.
  echo   Nao foi possivel instalar o uv automaticamente.
  echo   Verifique a conexao com a internet e execute este arquivo de novo.
  echo   Se o problema continuar, instale o uv seguindo https://docs.astral.sh/uv/
  pause
  exit /b 1
)

echo   [2/4] Instalando os componentes do programa.
echo         Na primeira vez sao cerca de 3 GB e pode demorar alguns minutos.
echo.
"%UV%" sync
if errorlevel 1 (
  echo.
  echo   Falha ao instalar os componentes.
  echo   Verifique a conexao com a internet e o espaco livre em disco, e execute este arquivo de novo.
  pause
  exit /b 1
)

echo.
echo   [3/4] Criando o atalho Transcritor na Area de Trabalho e no menu Iniciar...
".venv\Scripts\python.exe" -m transcritor.desktop.atalhos
if errorlevel 1 echo   Aviso: os atalhos nao foram criados. Para abrir o programa, execute este instalador de novo.

echo.
echo   [4/4] Abrindo o Transcritor. Na primeira vez ele baixa os modelos de IA, cerca de 3 GB,
echo         e mostra o andamento na propria janela.
".venv\Scripts\python.exe" -m transcritor.desktop.atalhos --abrir --preparar
echo.
echo   Pronto. Nas proximas vezes, use o atalho Transcritor na Area de Trabalho.
timeout /t 10 >nul
