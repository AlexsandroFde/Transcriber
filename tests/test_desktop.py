"""Abertura do aplicativo sem janela de console no Windows (atalho e lançador)."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from transcritor.desktop import atalhos, lancador

so_windows = pytest.mark.skipif(sys.platform != "win32", reason="atalhos e lançador existem só no Windows")


def _subsistema(exe: str | Path) -> int:
    """Subsistema do executável (cabeçalho PE): 2 = programa de janela, 3 = programa de console."""
    dados = Path(exe).read_bytes()
    pe = int.from_bytes(dados[0x3C:0x40], "little")
    return int.from_bytes(dados[pe + 92:pe + 94], "little")


def test_lancador_abre_o_aplicativo_no_ambiente_virtual():
    cmd, env = lancador.comando(r"C:\py\pythonw.exe", r"C:\app\.venv\Scripts\pythonw.exe", [r"C:\reuniao.mp4"])
    assert cmd == [r"C:\py\pythonw.exe", "-P", "-m", "transcritor.desktop", r"C:\reuniao.mp4"]
    assert env["__PYVENV_LAUNCHER__"] == r"C:\app\.venv\Scripts\pythonw.exe"


@so_windows
def test_atalho_chama_um_programa_sem_console(tmp_path):
    [caminho] = atalhos.criar([tmp_path])
    ler = "$a = (New-Object -ComObject WScript.Shell).CreateShortcut($env:TR_LNK); $a.TargetPath; $a.Arguments"
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ler], env={**os.environ, "TR_LNK": caminho},
                       capture_output=True, text=True, check=True)
    alvo, argumentos = r.stdout.splitlines()[:2]
    assert _subsistema(alvo) == 2
    assert argumentos == subprocess.list2cmdline(["-I", str(Path(sys.executable).with_name(atalhos.LANCADOR))])


@so_windows
def test_python_base_com_a_variavel_do_lancador_roda_no_ambiente_sem_console(tmp_path):
    saida = tmp_path / "sonda.txt"
    sonda = ("import ctypes, sys, transcritor; "
             "open(sys.argv[1], 'w').write(repr((sys.prefix, ctypes.windll.kernel32.GetConsoleWindow())))")
    pythonw = atalhos.comando()[0]
    _, env = lancador.comando(pythonw, str(Path(sys.executable).with_name("pythonw.exe")), [])
    subprocess.run([pythonw, "-c", sonda, str(saida)], env=env, timeout=120, check=True)
    prefixo, console = ast.literal_eval(saida.read_text())
    assert Path(prefixo) == Path(sys.prefix)
    assert console == 0
