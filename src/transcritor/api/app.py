"""Aplicação FastAPI: API REST em /api/v1, documentação em /docs e a interface gráfica em /."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from .. import __version__
from ..config import PREFIXO_API, Configuracoes, pasta_web
from ..servicos.contexto import Servicos
from . import documentacao, erros
from .rotas import roteador
from .seguranca import ProtecaoLocal

log = logging.getLogger("transcritor.api")


class _ArquivosEstaticos(StaticFiles):
    """Interface sem cache: depois de uma atualização, a janela já abre com a versão nova."""

    async def get_response(self, path: str, scope: Scope):
        resposta = await super().get_response(path, scope)
        resposta.headers["Cache-Control"] = "no-cache"
        return resposta


def criar_app(servicos: Servicos, ao_encerrar: Callable[[], None] | None = None) -> FastAPI:
    config: Configuracoes = servicos.config

    @asynccontextmanager
    async def ciclo(_app: FastAPI):
        await asyncio.to_thread(servicos.iniciar)
        try:
            yield
        finally:
            await asyncio.to_thread(servicos.encerrar)

    app = FastAPI(
        title=documentacao.TITULO, version=__version__, description=documentacao.DESCRICAO,
        openapi_tags=documentacao.TAGS, openapi_url=f"{PREFIXO_API}/openapi.json", docs_url=None, redoc_url=None,
        lifespan=ciclo,
    )
    app.state.servicos = servicos
    app.state.ao_encerrar = ao_encerrar

    if config.origens_extras:
        app.add_middleware(CORSMiddleware, allow_origins=list(config.origens_extras), allow_methods=["*"],
                           allow_headers=["*"])
    app.add_middleware(ProtecaoLocal, hosts_extras=config.hosts_extras, origens_extras=config.origens_extras)

    erros.registrar(app)
    app.include_router(roteador(), prefix=PREFIXO_API)
    documentacao.registrar(app)
    app.mount("/", _ArquivosEstaticos(directory=pasta_web(), html=True), name="interface")
    return app
