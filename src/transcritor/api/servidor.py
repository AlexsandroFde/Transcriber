"""Execução do servidor HTTP (Uvicorn), em primeiro plano ou numa thread do aplicativo.

`ServidorLocal` é usado pelo inicializador da janela: escolhe uma porta livre, sobe a API numa
thread, avisa quando ela está pronta e encerra tudo de forma ordenada (conexões de eventos,
tarefas em andamento e a porta) quando a janela é fechada.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable

import uvicorn

from ..config import PREFIXO_API, Configuracoes
from ..servicos.contexto import Servicos, criar_servicos
from .app import criar_app

log = logging.getLogger("transcritor.servidor")


def porta_livre(host: str, preferida: int) -> int:
    """A porta preferida, se estiver livre; senão, uma porta escolhida pelo sistema."""
    for porta in ([preferida] if preferida else []) + [0]:
        with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, porta))
                return s.getsockname()[1]
            except OSError:
                continue
    raise OSError("Nenhuma porta disponível")


def consultar_saude(url_base: str, tempo_limite: float = 2.0) -> dict | None:
    try:
        with urllib.request.urlopen(f"{url_base}{PREFIXO_API}/saude", timeout=tempo_limite) as r:
            dados = json.loads(r.read().decode("utf-8"))
            return dados if dados.get("aplicacao") == "transcritor" else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _config_uvicorn(app, host: str, porta: int) -> uvicorn.Config:
    return uvicorn.Config(app, host=host, port=porta, log_config=None, access_log=False, lifespan="on",
                          timeout_graceful_shutdown=3, timeout_keep_alive=5)


class ServidorLocal:
    def __init__(self, config: Configuracoes, modo: str = "desktop", ao_encerrar_pedido: Callable[[], None] | None = None):
        self.config = config
        self.modo = modo
        self.servicos: Servicos | None = None
        self.porta: int | None = None
        self._servidor: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._erro: BaseException | None = None
        self._ao_encerrar_pedido = ao_encerrar_pedido

    @property
    def url(self) -> str:
        host = self.config.host if self.config.host not in ("0.0.0.0", "::") else "127.0.0.1"
        return f"http://{host}:{self.porta}"

    def iniciar(self) -> None:
        self._erro = None
        self.porta = porta_livre(self.config.host, self.config.porta)
        self.servicos = criar_servicos(self.config, modo=self.modo)
        app = criar_app(self.servicos, ao_encerrar=self._ao_encerrar_pedido)
        self._servidor = uvicorn.Server(_config_uvicorn(app, self.config.host, self.porta))

        def rodar() -> None:
            try:
                self._servidor.run()  # type: ignore[union-attr]
            except BaseException as e:  # pragma: no cover - depende do sistema
                self._erro = e
                log.exception("O servidor parou com erro")

        self._thread = threading.Thread(target=rodar, name="servidor-api", daemon=True)
        self._thread.start()
        log.info("Servidor iniciando em %s", self.url)

    def aguardar_pronto(self, tempo_limite: float = 60.0) -> None:
        """Espera a API responder. Lança RuntimeError com a causa, se ela não subir."""
        limite = time.monotonic() + tempo_limite
        while time.monotonic() < limite:
            if self._erro is not None:
                raise RuntimeError(f"O serviço não conseguiu iniciar: {self._erro}") from self._erro
            if self._thread is not None and not self._thread.is_alive():
                raise RuntimeError("O serviço do Transcritor parou durante a inicialização. Veja o registro (log).")
            if self._servidor is not None and self._servidor.started and consultar_saude(self.url, 1.0):
                return
            time.sleep(0.1)
        raise RuntimeError("O serviço do Transcritor demorou demais para iniciar.")

    @property
    def ativo(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def parar(self, tempo_limite: float = 15.0) -> None:
        if self._servidor is None:
            return
        if self.servicos is not None:
            self.servicos.barramento.encerrar()  # fecha as conexões de eventos para o servidor não esperar
        self._servidor.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=tempo_limite)
            if self._thread.is_alive():  # pragma: no cover
                log.warning("O servidor não terminou a tempo; forçando o encerramento.")
                self._servidor.force_exit = True
                self._thread.join(timeout=5)
        log.info("Servidor encerrado")
        self._servidor = None


def executar(config: Configuracoes, verificar_ao_iniciar: bool = True) -> int:
    """`transcritor servidor`: só a API, em primeiro plano (Ctrl+C encerra)."""
    servicos = criar_servicos(config, modo="servidor", verificar_ao_iniciar=verificar_ao_iniciar)
    servidor: uvicorn.Server | None = None

    def encerrar() -> None:
        servicos.barramento.encerrar()
        if servidor is not None:
            servidor.should_exit = True

    app = criar_app(servicos, ao_encerrar=encerrar)
    porta = porta_livre(config.host, config.porta)
    if config.porta and porta != config.porta:
        log.warning("A porta %d está ocupada; usando %d.", config.porta, porta)
    servidor = uvicorn.Server(_config_uvicorn(app, config.host, porta))
    exibido = "127.0.0.1" if config.host in ("0.0.0.0", "::") else config.host
    log.info("API do Transcritor em http://%s:%d%s  (documentação: http://%s:%d/docs)", exibido, porta, PREFIXO_API,
             exibido, porta)
    servidor.run()
    return 0
