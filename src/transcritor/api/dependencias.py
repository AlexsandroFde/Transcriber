"""Dependências injetadas nas rotas."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from ..servicos.contexto import Servicos


def _servicos(request: Request) -> Servicos:
    return request.app.state.servicos


ServicosDep = Annotated[Servicos, Depends(_servicos)]
