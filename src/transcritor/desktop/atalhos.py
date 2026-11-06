"""Cria (ou atualiza) os atalhos "Transcritor" na Área de Trabalho e no menu Iniciar (Windows).

Chamado pelo instalar.bat:  python -m transcritor.desktop.atalhos
Um vídeo arrastado sobre o atalho abre o Transcritor com o arquivo já escolhido.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ..config import NOME_APLICATIVO, pasta_programa, pasta_web

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$pastas = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
if ($env:TR_PASTAS) { $pastas = $env:TR_PASTAS -split '\|' }
foreach ($pasta in $pastas) {
  $atalho = $shell.CreateShortcut((Join-Path $pasta ($env:TR_NOME + '.lnk')))
  $atalho.TargetPath = $env:TR_ALVO
  $atalho.WorkingDirectory = $env:TR_PASTA
  $atalho.IconLocation = $env:TR_ICONE + ',0'
  $atalho.Description = $env:TR_DESCRICAO
  $atalho.Save()
  Write-Output (Join-Path $pasta ($env:TR_NOME + '.lnk'))
}
"""


def executavel() -> Path:
    """O inicializador sem console gerado pela instalação (.venv/Scripts/transcritor-app.exe)."""
    return Path(sys.executable).with_name("transcritor-app.exe")


def criar(pastas: list[Path] | None = None) -> list[str]:
    """Cria os atalhos. `pastas` substitui Área de Trabalho e menu Iniciar (usado em testes)."""
    if sys.platform != "win32":
        raise SystemExit("Atalhos só são criados no Windows. Em outros sistemas, use: transcritor app")
    alvo = executavel()
    if not alvo.is_file():
        raise SystemExit(f"Inicializador não encontrado: {alvo}. Rode 'uv sync' na pasta do programa.")
    env = dict(os.environ, TR_NOME=NOME_APLICATIVO, TR_ALVO=str(alvo),
               TR_PASTA=str(pasta_programa() or alvo.parent), TR_ICONE=str(pasta_web() / "icone.ico"),
               TR_DESCRICAO="Transcrição de reuniões em português, no seu computador",
               TR_PASTAS="|".join(str(p) for p in pastas) if pastas else "")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _SCRIPT], env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=subprocess.CREATE_NO_WINDOW)
    if r.returncode != 0:
        raise SystemExit(f"Não foi possível criar os atalhos: {r.stderr.strip()}")
    return [linha for linha in r.stdout.splitlines() if linha.strip()]


if __name__ == "__main__":
    for caminho in criar():
        print(f"Atalho criado: {caminho}")
