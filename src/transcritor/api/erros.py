"""Formato padrão de erro da API e tradução das exceções em respostas HTTP.

Toda resposta de erro tem o mesmo corpo:

    {"erro": {"codigo": "arquivo_nao_encontrado", "status": 422,
              "mensagem": "Arquivo não encontrado: C:\\...\\reuniao.mp4",
              "dica": "Verifique se o arquivo foi movido...",
              "campos": [{"campo": "arquivos[0]", "mensagem": "..."}]}}
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..erros import Conflito, EntradaInvalida, ErroTranscritor, Indisponivel, NaoEncontrado

log = logging.getLogger("transcritor.api")


class CampoErro(BaseModel):
    campo: str = Field(..., examples=["arquivos[0]"])
    mensagem: str = Field(..., examples=["Campo obrigatório."])


class DetalheErro(BaseModel):
    codigo: str = Field(..., description="Código estável, para tratamento por integrações.",
                        examples=["arquivo_nao_encontrado"])
    status: int = Field(..., description="Código HTTP da resposta.", examples=[422])
    mensagem: str = Field(..., description="O que aconteceu, em linguagem simples.")
    dica: str | None = Field(None, description="Como resolver, quando possível.")
    campos: list[CampoErro] = Field(default_factory=list, description="Erros de validação por campo.")


class RespostaErro(BaseModel):
    erro: DetalheErro


STATUS_POR_TIPO: list[tuple[type[ErroTranscritor], int]] = [
    (EntradaInvalida, 422), (NaoEncontrado, 404), (Conflito, 409), (Indisponivel, 503)]

DESCRICOES = {
    400: "Requisição recusada (por exemplo, nome de host não permitido).",
    403: "Origem não permitida: a API só aceita chamadas da própria interface ou de programas locais.",
    404: "Recurso não encontrado.",
    409: "A operação conflita com o estado atual (tarefa já encerrada, arquivo em uso...).",
    413: "Arquivo grande demais.",
    422: "Dados inválidos: o corpo da resposta indica o campo e o motivo.",
    503: "O serviço está sendo encerrado ou um recurso do sistema não está disponível.",
}


def respostas(*status: int) -> dict[int | str, dict[str, Any]]:
    """Documentação OpenAPI das respostas de erro de uma rota."""
    return {s: {"model": RespostaErro, "description": DESCRICOES.get(s, "Erro.")} for s in status}


def resposta_erro(status: int, codigo: str, mensagem: str, dica: str | None = None,
                  campos: list[CampoErro] | None = None, headers: dict | None = None) -> JSONResponse:
    corpo = RespostaErro(erro=DetalheErro(codigo=codigo, status=status, mensagem=mensagem, dica=dica,
                                          campos=campos or []))
    return JSONResponse(corpo.model_dump(), status_code=status, headers=headers)


# -- validação ---------------------------------------------------------------

_MENSAGENS = {
    "missing": "Campo obrigatório.",
    "extra_forbidden": "Campo não reconhecido.",
    "string_type": "Deve ser um texto.",
    "int_type": "Deve ser um número inteiro.",
    "int_parsing": "Deve ser um número inteiro.",
    "int_from_float": "Deve ser um número inteiro.",
    "float_type": "Deve ser um número.",
    "float_parsing": "Deve ser um número.",
    "bool_type": "Deve ser true ou false.",
    "bool_parsing": "Deve ser true ou false.",
    "list_type": "Deve ser uma lista.",
    "dict_type": "Deve ser um objeto JSON.",
    "model_type": "Deve ser um objeto JSON.",
    "model_attributes_type": "Deve ser um objeto JSON.",
    "greater_than_equal": "Deve ser maior ou igual a {ge}.",
    "greater_than": "Deve ser maior que {gt}.",
    "less_than_equal": "Deve ser menor ou igual a {le}.",
    "less_than": "Deve ser menor que {lt}.",
    "string_too_short": "Deve ter pelo menos {min_length} caractere(s).",
    "string_too_long": "Deve ter no máximo {max_length} caracteres.",
    "too_short": "Deve ter pelo menos {min_length} item(ns).",
    "too_long": "Deve ter no máximo {max_length} itens.",
    "literal_error": "Valor inválido. Use um destes: {expected}.",
    "enum": "Valor inválido. Use um destes: {expected}.",
    "string_pattern_mismatch": "Formato inválido.",
    "json_invalid": "JSON inválido: {error}.",
    "json_type": "JSON inválido.",
    "union_tag_invalid": "Tipo inválido.",
    "datetime_parsing": "Data e hora inválidas.",
}
_MENSAGENS_CAMPO = {
    "faixa_audio": {"string_pattern_mismatch": "Use o número da faixa (0 é a primeira) ou \"todas\"."},
    "modelo": {"string_pattern_mismatch": "O nome do modelo não pode conter quebras de linha."},
    "modelo_revisao": {"string_pattern_mismatch": "O nome do modelo não pode conter quebras de linha."},
}


def _campo(loc: tuple | list) -> str:
    partes = [p for p in loc if p not in ("body", "query", "path", "header")]
    texto = ""
    for p in partes:
        texto += f"[{p}]" if isinstance(p, int) else (f".{p}" if texto else str(p))
    return texto or "corpo"


def _mensagem(erro: dict) -> str:
    tipo = erro.get("type", "")
    loc = erro.get("loc") or ()
    nome = next((p for p in reversed(loc) if isinstance(p, str)), "")
    especifica = _MENSAGENS_CAMPO.get(nome, {}).get(tipo)
    if especifica:
        return especifica
    if tipo == "value_error":
        return str(erro.get("msg", "")).removeprefix("Value error, ")
    modelo = _MENSAGENS.get(tipo)
    if modelo is None:
        return str(erro.get("msg", "Valor inválido."))
    ctx = dict(erro.get("ctx") or {})
    if "expected" in ctx:
        ctx["expected"] = str(ctx["expected"]).replace("'", "").replace(" or ", ", ")
    try:
        return modelo.format(**ctx)
    except (KeyError, IndexError):
        return modelo


def campos_validacao(erros: list[dict]) -> list[CampoErro]:
    return [CampoErro(campo=_campo(e.get("loc") or ()), mensagem=_mensagem(e)) for e in erros]


# -- registro ------------------------------------------------------------------


def registrar(app: FastAPI) -> None:
    @app.exception_handler(ErroTranscritor)
    async def _erro_dominio(_req: Request, exc: ErroTranscritor) -> JSONResponse:
        status = next((s for tipo, s in STATUS_POR_TIPO if isinstance(exc, tipo)), 500)
        if status >= 500:
            log.error("Erro %s: %s", exc.codigo, exc.mensagem)
        return resposta_erro(status, exc.codigo, exc.mensagem, exc.dica,
                             [CampoErro(campo=c.campo, mensagem=c.mensagem) for c in exc.campos])

    @app.exception_handler(RequestValidationError)
    async def _validacao(_req: Request, exc: RequestValidationError) -> JSONResponse:
        campos = campos_validacao(list(exc.errors()))
        mensagem = "Os dados enviados são inválidos."
        if len(campos) == 1:
            mensagem = f"Dado inválido em {campos[0].campo}: {campos[0].mensagem}"
        return resposta_erro(422, "dados_invalidos", mensagem, "Corrija os campos indicados e tente de novo.", campos)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_req: Request, exc: StarletteHTTPException) -> JSONResponse:
        codigos = {404: ("rota_nao_encontrada", "Endereço não encontrado na API."),
                   405: ("metodo_nao_permitido", "Método HTTP não permitido neste endereço."),
                   413: ("arquivo_grande_demais", "O conteúdo enviado é grande demais.")}
        codigo, mensagem = codigos.get(exc.status_code, ("erro_http", str(exc.detail)))
        if exc.status_code not in codigos and isinstance(exc.detail, str):
            mensagem = exc.detail
        dica = "Consulte a documentação em /docs." if exc.status_code in (404, 405) else None
        return resposta_erro(exc.status_code, codigo, mensagem, dica, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _inesperado(_req: Request, exc: Exception) -> JSONResponse:
        log.exception("Erro inesperado na API")
        return resposta_erro(500, "erro_interno", "Ocorreu um erro inesperado no Transcritor.",
                             "Tente de novo. Se o problema continuar, os detalhes estão no registro (log) do "
                             "aplicativo, em Configurações > Sobre.")
