"""Barramento de eventos: entrega mudanças de estado a quem estiver ouvindo.

Publicadores rodam em threads comuns (execução das tarefas); assinantes podem ser:
  * filas assíncronas (uma por conexão SSE em `GET /api/v1/eventos`), alimentadas com
    `call_soon_threadsafe` no laço de eventos do servidor;
  * funções síncronas (o inicializador da área de trabalho, para trazer a janela à frente).

Eventos são dicionários `{"tipo": str, "dados": dict, "momento": iso}`.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any

log = logging.getLogger("transcritor.eventos")

FIM = {"tipo": "_fim"}


class Assinatura:
    def __init__(self, laco: asyncio.AbstractEventLoop, tamanho: int = 1000):
        self.laco = laco
        self.fila: asyncio.Queue[dict] = asyncio.Queue(maxsize=tamanho)

    def _colocar(self, evento: dict) -> None:
        try:
            self.fila.put_nowait(evento)
        except asyncio.QueueFull:
            # Cliente lento: descarta o mais antigo; o estado completo sempre pode ser relido pela API.
            try:
                self.fila.get_nowait()
                self.fila.put_nowait(evento)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass

    def entregar(self, evento: dict) -> None:
        try:
            self.laco.call_soon_threadsafe(self._colocar, evento)
        except RuntimeError:
            pass  # laço encerrado


class Barramento:
    def __init__(self) -> None:
        self._assinaturas: set[Assinatura] = set()
        self._ouvintes: list[Callable[[dict], None]] = []
        self._lock = threading.Lock()
        self._encerrado = False

    def assinar(self, laco: asyncio.AbstractEventLoop | None = None) -> Assinatura:
        assinatura = Assinatura(laco or asyncio.get_running_loop())
        with self._lock:
            self._assinaturas.add(assinatura)
            if self._encerrado:
                assinatura.entregar(FIM)
        return assinatura

    def cancelar(self, assinatura: Assinatura) -> None:
        with self._lock:
            self._assinaturas.discard(assinatura)

    def ouvir(self, funcao: Callable[[dict], None]) -> None:
        with self._lock:
            self._ouvintes.append(funcao)

    @property
    def assinantes(self) -> int:
        with self._lock:
            return len(self._assinaturas)

    def publicar(self, tipo: str, dados: dict[str, Any] | None = None) -> None:
        evento = {"tipo": tipo, "dados": dados or {}, "momento": datetime.now().astimezone().isoformat()}
        with self._lock:
            assinaturas = list(self._assinaturas)
            ouvintes = list(self._ouvintes)
        for a in assinaturas:
            a.entregar(evento)
        for f in ouvintes:
            try:
                f(evento)
            except Exception:
                log.exception("Falha em ouvinte de eventos")

    def encerrar(self) -> None:
        """Fecha todas as conexões abertas (o servidor pode então terminar sem esperar)."""
        with self._lock:
            self._encerrado = True
            assinaturas = list(self._assinaturas)
        for a in assinaturas:
            a.entregar(FIM)
