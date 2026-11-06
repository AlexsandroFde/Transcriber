"""Lançador sem console: é o que o atalho "Transcritor" executa no Windows.

O atalho roda este arquivo no pythonw.exe do Python base, que é um programa de janela: o Windows não
cria console para ele. Daqui o aplicativo é iniciado no mesmo pythonw.exe, com a variável
__PYVENV_LAUNCHER__ apontando para o ambiente virtual, que é como o lançador do próprio ambiente o ativa.

Por que não usar o pythonw.exe do ambiente virtual: o uv o cria como cópia do python.exe, um programa de
console, e o Windows abriria uma janela de console junto com o aplicativo.

`python -m transcritor.desktop.atalhos` copia este arquivo para a pasta Scripts do ambiente
(transcritor-app.pyw, ao lado do pythonw.exe do ambiente). Ele roda antes de o ambiente estar ativo,
então só usa a biblioteca padrão.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def comando(python_base: str, lancador_venv: str, argumentos: list[str]) -> tuple[list[str], dict[str, str]]:
    """(comando, variáveis de ambiente) que abrem o aplicativo dentro do ambiente virtual.

    `-P` deixa a pasta de trabalho (a do programa) fora do sys.path.
    """
    env = dict(os.environ, __PYVENV_LAUNCHER__=lancador_venv)
    return [python_base, "-P", "-m", "transcritor.desktop", *argumentos], env


def _python_base() -> str:
    """O pythonw.exe do Python base (o deste processo, quando aberto pelo atalho)."""
    base = Path(getattr(sys, "_base_executable", None) or sys.executable)
    pythonw = base.with_name("pythonw.exe")
    return str(pythonw if pythonw.is_file() else base)


def _avisar(mensagem: str) -> None:
    import ctypes

    ctypes.windll.user32.MessageBoxW(0, mensagem, "Transcritor", 0x10)  # MB_ICONERROR


def main() -> int:
    lancador_venv = Path(os.path.abspath(__file__)).with_name("pythonw.exe")
    if not (lancador_venv.parent.parent / "pyvenv.cfg").is_file():
        _avisar("O ambiente do Transcritor não foi encontrado.\n\n"
                "Execute o instalar.bat, na pasta do programa, de novo.")
        return 1
    cmd, env = comando(_python_base(), str(lancador_venv), sys.argv[1:])
    try:
        proc = subprocess.Popen(cmd, env=env)
    except OSError as e:
        _avisar(f"Não foi possível abrir o Transcritor.\n\n{e}")
        return 1
    # Quem o atalho abriu pode trazer uma janela para a frente; repassa essa permissão ao aplicativo.
    import ctypes

    ctypes.windll.user32.AllowSetForegroundWindow(proc.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
