"""Instância única do aplicativo.

Abrir o atalho com o Transcritor já aberto não inicia outro servidor nem outra fila de
tarefas: o inicializador traz a janela existente para a frente e entrega os arquivos
recebidos (por exemplo, um vídeo arrastado sobre o atalho).

O bloqueio é um trava de arquivo do sistema operacional: se o programa terminar de forma
abrupta, o sistema solta a trava sozinho e a próxima abertura funciona normalmente.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from ..config import PREFIXO_API, Configuracoes

log = logging.getLogger("transcritor.desktop")


class Instancia:
    def __init__(self, config: Configuracoes):
        self.config = config
        self.arquivo_trava = config.pasta_dados / "instancia.lock"
        self.arquivo_info = config.arquivo_instancia
        self._trava = None

    def adquirir(self) -> bool:
        self.arquivo_trava.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.arquivo_trava, "a+b")
        try:
            f.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self._trava = f
        return True

    def registrar(self, url: str) -> None:
        dados = {"url": url, "pid": os.getpid(), "iniciado_em": datetime.now().astimezone().isoformat()}
        self.arquivo_info.write_text(json.dumps(dados), encoding="utf-8")

    def liberar(self) -> None:
        if self._trava is None:
            return
        try:
            self.arquivo_info.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            if sys.platform == "win32":
                import msvcrt

                self._trava.seek(0)
                msvcrt.locking(self._trava.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self._trava.close()
        self._trava = None

    def entregar(self, arquivos: list[str], tentativas: int = 8) -> bool:
        """Pede à instância aberta que venha para a frente (com os arquivos). True se ela respondeu."""
        import time

        for _ in range(tentativas):  # a outra instância pode estar terminando de iniciar
            try:
                info = json.loads(self.arquivo_info.read_text(encoding="utf-8"))
                url = info["url"]
                if sys.platform == "win32":
                    # Quem está em primeiro plano (esta instância, recém-aberta) autoriza a outra a vir para a frente.
                    import ctypes

                    ctypes.windll.user32.AllowSetForegroundWindow(int(info.get("pid") or 0xFFFFFFFF))
                pedido = urllib.request.Request(f"{url}{PREFIXO_API}/sistema/ativar", method="POST",
                                                data=json.dumps({"arquivos": arquivos}).encode("utf-8"),
                                                headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(pedido, timeout=2) as r:
                    return r.status == 202
            except (OSError, ValueError, KeyError, urllib.error.URLError):
                time.sleep(0.5)
        return False


def arquivos_dos_argumentos(argv: list[str]) -> list[str]:
    """Arquivos existentes passados ao inicializador (ignora opções como --preparar)."""
    saida = []
    for a in argv:
        if a.startswith("--"):
            continue
        p = Path(a.strip('"'))
        if p.is_file():
            saida.append(str(p.resolve()))
    return saida
