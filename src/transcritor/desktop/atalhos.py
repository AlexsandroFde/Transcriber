"""Atalhos "Transcritor" na Área de Trabalho e no menu Iniciar (Windows), e a abertura sem console.

Chamado pelo instalar.bat:
  python -m transcritor.desktop.atalhos                       cria (ou atualiza) os atalhos
  python -m transcritor.desktop.atalhos --abrir [--preparar]  abre o aplicativo como o atalho faz
Um vídeo arrastado sobre o atalho abre o Transcritor com o arquivo já escolhido.

O atalho chama o pythonw.exe do Python base com o lançador (lancador.py), e não o pythonw.exe do
ambiente virtual: o uv cria esse como programa de console, e o Windows abriria uma janela de console
junto com o aplicativo.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from ..config import NOME_APLICATIVO, pasta_programa, pasta_web

# Nome da cópia do lançador na pasta Scripts do ambiente virtual.
LANCADOR = "transcritor-app.pyw"

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$pastas = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
if ($env:TR_PASTAS) { $pastas = $env:TR_PASTAS -split '\|' }
foreach ($pasta in $pastas) {
  $atalho = $shell.CreateShortcut((Join-Path $pasta ($env:TR_NOME + '.lnk')))
  $atalho.TargetPath = $env:TR_ALVO
  $atalho.Arguments = $env:TR_ARGUMENTOS
  $atalho.WorkingDirectory = $env:TR_PASTA
  $atalho.IconLocation = $env:TR_ICONE + ',0'
  $atalho.Description = $env:TR_DESCRICAO
  $atalho.Save()
  Write-Output (Join-Path $pasta ($env:TR_NOME + '.lnk'))
}
"""

_SO_WINDOWS = "Atalhos só são criados no Windows. Em outros sistemas, use: transcritor app"


def _pasta_trabalho() -> Path:
    return pasta_programa() or Path(sys.executable).parent


def comando(argumentos: Sequence[str] = ()) -> list[str]:
    """O comando do atalho: o pythonw.exe do Python base roda o lançador do ambiente virtual, sem console."""
    if sys.prefix == sys.base_prefix:
        raise SystemExit("Rode pelo ambiente virtual do programa (.venv). Execute 'uv sync' na pasta do programa.")
    pythonw = Path(getattr(sys, "_base_executable", None) or sys.executable).with_name("pythonw.exe")
    if not pythonw.is_file():
        raise SystemExit(f"Python sem console não encontrado: {pythonw}")
    return [str(pythonw), "-I", str(Path(sys.executable).with_name(LANCADOR)), *argumentos]


def instalar_lancador() -> Path:
    """Copia o lançador para a pasta Scripts do ambiente virtual (ao lado do pythonw.exe do ambiente)."""
    destino = Path(sys.executable).with_name(LANCADOR)
    shutil.copyfile(Path(__file__).with_name("lancador.py"), destino)
    return destino


def criar(pastas: list[Path] | None = None) -> list[str]:
    """Cria os atalhos. `pastas` substitui Área de Trabalho e menu Iniciar (usado em testes)."""
    if sys.platform != "win32":
        raise SystemExit(_SO_WINDOWS)
    alvo, *argumentos = comando()
    env = dict(os.environ, TR_NOME=NOME_APLICATIVO, TR_ALVO=alvo, TR_ARGUMENTOS=subprocess.list2cmdline(argumentos),
               TR_PASTA=str(_pasta_trabalho()), TR_ICONE=str(pasta_web() / "icone.ico"),
               TR_DESCRICAO="Transcrição de reuniões em português, no seu computador",
               TR_PASTAS="|".join(str(p) for p in pastas) if pastas else "")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _SCRIPT], env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=subprocess.CREATE_NO_WINDOW)
    if r.returncode != 0:
        raise SystemExit(f"Não foi possível criar os atalhos: {r.stderr.strip()}")
    return [linha for linha in r.stdout.splitlines() if linha.strip()]


def abrir(argumentos: Sequence[str] = ()) -> None:
    """Abre o aplicativo do mesmo jeito que o atalho, sem console (usado pelo instalar.bat)."""
    subprocess.Popen(comando(argumentos), cwd=_pasta_trabalho())


def main(argv: Sequence[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if sys.platform != "win32":
        raise SystemExit(_SO_WINDOWS)
    instalar_lancador()
    if argv[:1] == ["--abrir"]:
        abrir(argv[1:])
        return
    for caminho in criar():
        print(f"Atalho criado: {caminho}")


if __name__ == "__main__":
    main()
