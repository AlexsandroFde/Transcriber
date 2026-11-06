"""Rotas de mídia: inspeção de gravações e envio de arquivos."""

from __future__ import annotations

from pathlib import Path as Caminho
from typing import Annotated

from fastapi import APIRouter, File, Path, Query, Response, UploadFile, status
from starlette.concurrency import run_in_threadpool

from ...servicos.contratos import ArquivoEnviado, InfoMidia, ListaEnvios
from ...servicos.midia import informacoes
from ..dependencias import ServicosDep
from ..erros import respostas

rotas = APIRouter(prefix="/midia", tags=["Mídia"])


@rotas.get("/informacoes", response_model=InfoMidia, summary="Inspecionar uma gravação", responses=respostas(404, 422),
           description="Duração, tamanho, se há vídeo e as faixas de áudio (com índice, canais, codec, idioma e título), "
                       "sem processar nada. Use para escolher `faixa_audio` quando o vídeo tem várias faixas (gravações "
                       "do OBS, por exemplo). Também informa onde os resultados serão gravados por padrão.")
def inspecionar(caminho: Annotated[str, Query(min_length=1, max_length=1000, description="Caminho do arquivo.",
                                              examples=["C:\\Users\\ana\\Videos\\reuniao.mp4"])],
                pasta_saida: Annotated[str | None, Query(max_length=1000)] = None) -> InfoMidia:
    return informacoes(caminho, pasta_saida)


@rotas.post("/envios", response_model=ArquivoEnviado, status_code=status.HTTP_201_CREATED,
            summary="Enviar uma gravação", responses=respostas(422),
            description="Para programas que não compartilham o disco com o Transcritor: envie o arquivo "
                        "(`multipart/form-data`, campo `arquivo`) e use o `caminho` devolvido em "
                        "`POST /api/v1/transcricoes`. Os resultados ficam, por padrão, ao lado do arquivo enviado, e "
                        "podem ser baixados por `GET /api/v1/transcricoes/{id}/arquivos/{tipo}`.")
async def enviar(servicos: ServicosDep, arquivo: Annotated[UploadFile, File(description="Vídeo ou áudio.")]
                 ) -> ArquivoEnviado:
    try:
        return await run_in_threadpool(servicos.envios.salvar, arquivo.filename or "gravacao", arquivo.file)
    finally:
        await arquivo.close()


@rotas.get("/envios", response_model=ListaEnvios, summary="Listar envios")
def listar(servicos: ServicosDep) -> ListaEnvios:
    itens = servicos.envios.listar()
    return ListaEnvios(itens=itens, total=len(itens))


@rotas.delete("/envios/{id}", status_code=status.HTTP_204_NO_CONTENT, summary="Apagar um envio",
              responses=respostas(404, 409),
              description="Apaga o arquivo enviado. Resultados de transcrições feitas a partir dele são preservados. "
                          "Responde **409** se ele estiver em uso por uma transcrição na fila ou em andamento.")
def apagar(id: Annotated[str, Path(pattern=r"^[0-9a-f]{12}$")], servicos: ServicosDep) -> Response:
    servicos.envios.remover(id, em_uso=lambda arq: servicos.envio_em_uso(Caminho(arq)))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
