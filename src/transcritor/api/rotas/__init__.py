"""Rotas da API, agrupadas por módulo funcional."""

from fastapi import APIRouter

from . import ambiente, configuracao, eventos, midia, participantes, sistema, tarefas, transcricoes


def roteador() -> APIRouter:
    r = APIRouter()
    for modulo in (transcricoes, participantes, tarefas, eventos, midia, ambiente, configuracao, sistema):
        r.include_router(modulo.rotas)
    return r
