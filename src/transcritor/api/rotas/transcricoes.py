"""Rotas das transcrições: criação (assíncrona), histórico, conteúdo, relatório, arquivos e mídia."""

from __future__ import annotations

import mimetypes
from typing import Annotated

from fastapi import APIRouter, Body, Path, Query, Response, status
from fastapi.responses import FileResponse

from ...servicos.contratos import (
    ConteudoTranscricao,
    ListaTranscricoes,
    PedidoImportacao,
    PedidoTranscricao,
    RelatorioConferencia,
    TarefasCriadas,
    TipoArquivo,
    TranscricaoDetalhe,
    TranscricaoResumo,
)
from ..dependencias import ServicosDep
from ..erros import respostas

rotas = APIRouter(prefix="/transcricoes", tags=["Transcrições"])

IdTranscricao = Annotated[str, Path(description="Identificador da transcrição.", examples=["9a1e3c5b7f20d4e6"],
                                    pattern=r"^[0-9a-f]{16}$")]

_EXEMPLOS_PEDIDO = {
    "simples": {"summary": "Só o arquivo", "description": "Todas as opções no padrão.",
                "value": {"arquivos": ["C:\\Users\\ana\\Videos\\reuniao.mp4"]}},
    "completo": {"summary": "Com participantes, assunto e glossário",
                 "description": "As informações opcionais que mais melhoram o resultado.",
                 "value": {"arquivos": ["C:\\Users\\ana\\Videos\\conselho.mp4"], "participantes": 5,
                           "contexto": "Reunião do conselho sobre o orçamento 2027",
                           "glossario": ["Instituto Iracema", "SIGEP", "LGPD"],
                           "pasta_saida": "C:\\Transcricoes", "formatos": ["docx", "srt", "json"]}},
    "lote": {"summary": "Vários arquivos", "description": "Cada arquivo vira uma tarefa; elas rodam em sequência.",
             "value": {"arquivos": ["C:\\Videos\\parte1.mp4", "C:\\Videos\\parte2.mp4"], "faixa_audio": "todas"}},
    "rapido": {"summary": "Sem placa de vídeo", "description": "Modelo mais rápido, sem o segundo passo.",
               "value": {"arquivos": ["C:\\Videos\\reuniao.mp4"], "modelo": "large-v3-turbo", "revisao": False}},
}

_MIME = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         "md": "text/markdown; charset=utf-8", "relatorio": "text/markdown; charset=utf-8",
         "txt": "text/plain; charset=utf-8", "log": "text/plain; charset=utf-8", "srt": "application/x-subrip",
         "vtt": "text/vtt; charset=utf-8", "json": "application/json"}


@rotas.post(
    "", status_code=status.HTTP_202_ACCEPTED, response_model=TarefasCriadas, summary="Transcrever gravações",
    responses=respostas(409, 422, 503),
    description="Valida o pedido e coloca uma tarefa de transcrição na fila para cada arquivo. A resposta chega na "
                "hora; o processamento continua em segundo plano. Acompanhe cada tarefa por "
                "`GET /api/v1/tarefas/{id}` ou pelos eventos em `GET /api/v1/eventos`.\n\n"
                "Antes de aceitar, a API confere se cada arquivo existe, se tem áudio e se a faixa escolhida existe "
                "(**422** em caso de problema), e se o mesmo arquivo já não está na fila (**409**). O cabeçalho "
                "`Location` aponta para a primeira tarefa.")
def criar(pedido: Annotated[PedidoTranscricao, Body(openapi_examples=_EXEMPLOS_PEDIDO)], servicos: ServicosDep,
          response: Response) -> TarefasCriadas:
    tarefas = servicos.transcricoes.criar(pedido)
    response.headers["Location"] = f"/api/v1/tarefas/{tarefas[0].id}"
    return TarefasCriadas(tarefas=tarefas)


@rotas.get("", response_model=ListaTranscricoes, summary="Listar transcrições",
           description="Histórico das transcrições concluídas ou importadas, da mais recente para a mais antiga. "
                       "`disponivel=false` indica que a pasta da transcrição foi movida ou apagada.")
def listar(servicos: ServicosDep,
           busca: Annotated[str | None, Query(max_length=200, description="Filtra pelo nome do arquivo ou de "
                                                                          "participantes.")] = None
           ) -> ListaTranscricoes:
    itens = servicos.transcricoes.listar(busca)
    return ListaTranscricoes(itens=itens, total=len(itens))


@rotas.post("/importacoes", response_model=TranscricaoResumo, status_code=status.HTTP_201_CREATED,
            summary="Abrir uma transcrição existente", responses={200: {"model": TranscricaoResumo,
                                                                       "description": "Já estava no histórico."},
                                                                  **respostas(404, 422)},
            description="Inclui no histórico um arquivo .json gerado pelo Transcritor (inclusive pela versão antiga, "
                        "com o .bat, ou pela linha de comando), para nomear participantes, exportar ou consultar. "
                        "Responde **201** quando inclui e **200** quando o arquivo já estava no histórico.")
def importar(pedido: PedidoImportacao, servicos: ServicosDep, response: Response) -> TranscricaoResumo:
    resumo, criada = servicos.transcricoes.importar(pedido.caminho)
    if not criada:
        response.status_code = status.HTTP_200_OK
    return resumo


@rotas.get("/{id}", response_model=TranscricaoDetalhe, summary="Detalhes de uma transcrição",
           responses=respostas(404, 422),
           description="Arquivo de origem, processamento, participantes, indicadores de qualidade e a lista de "
                       "arquivos gerados (com links de download).")
def obter(id: IdTranscricao, servicos: ServicosDep) -> TranscricaoDetalhe:
    return servicos.transcricoes.obter(id)


@rotas.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remover do histórico",
              responses=respostas(404),
              description="Remove a transcrição do histórico. **Os arquivos no disco são mantidos**; ela pode ser "
                          "incluída de novo com `POST /api/v1/transcricoes/importacoes`.")
def remover(id: IdTranscricao, servicos: ServicosDep) -> Response:
    servicos.transcricoes.remover(id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@rotas.get("/{id}/conteudo", response_model=ConteudoTranscricao, summary="Texto da transcrição",
           responses=respostas(404, 422),
           description="Parágrafos (blocos) por participante, com início e fim em segundos. Cada bloco traz os "
                       "trechos separados por tipo (`texto`, `incerto`, `marcador`), para destacar o que precisa de "
                       "conferência, e o texto corrido como nos arquivos .md e .txt.")
def conteudo(id: IdTranscricao, servicos: ServicosDep) -> ConteudoTranscricao:
    return servicos.transcricoes.conteudo(id)


@rotas.get("/{id}/relatorio", response_model=RelatorioConferencia, summary="Relatório de conferência",
           responses=respostas(404, 422),
           description="O conteúdo do arquivo `_relatorio.md` em formato estruturado: processamento, tempo de fala "
                       "por participante, indicadores de qualidade, pontos para ouvir de novo (trechos incertos, "
                       "inaudíveis e frases descartadas), sugestões de nomes e o índice de menções a valores, datas, "
                       "prazos, horários, percentuais e encaminhamentos. Todas as citações são literais.")
def relatorio(id: IdTranscricao, servicos: ServicosDep) -> RelatorioConferencia:
    return servicos.transcricoes.relatorio(id)


@rotas.get("/{id}/arquivos/{tipo}", summary="Baixar um arquivo gerado", response_class=FileResponse,
           responses={200: {"description": "O arquivo.", "content": {
               "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {},
               "text/markdown": {}, "text/plain": {}, "application/x-subrip": {}, "text/vtt": {},
               "application/json": {}}}, **respostas(404)},
           description="`tipo`: `docx`, `md`, `txt`, `srt`, `vtt`, `json`, `relatorio` (o `_relatorio.md`) ou `log` "
                       "(registro técnico do processamento). Com `baixar=false`, o arquivo é exibido em vez de "
                       "baixado.")
def baixar(id: IdTranscricao, tipo: TipoArquivo, servicos: ServicosDep,
           baixar: Annotated[bool, Query(description="Enviar como anexo (download).")] = True) -> FileResponse:
    caminho = servicos.transcricoes.arquivo(id, tipo)
    return FileResponse(caminho, media_type=_MIME.get(tipo), filename=caminho.name,
                        content_disposition_type="attachment" if baixar else "inline")


@rotas.get("/{id}/midia", summary="Gravação original", response_class=FileResponse,
           responses={200: {"description": "A gravação (aceita o cabeçalho Range, para tocar a partir de um ponto).",
                            "content": {"video/mp4": {}, "audio/mpeg": {}}}, **respostas(404)},
           description="A gravação que deu origem à transcrição, para ouvir os pontos de conferência. Responde "
                       "**404** se ela foi movida ou apagada.")
def midia(id: IdTranscricao, servicos: ServicosDep) -> FileResponse:
    caminho = servicos.transcricoes.midia(id)
    tipo = mimetypes.guess_type(caminho.name)[0] or "application/octet-stream"
    return FileResponse(caminho, media_type=tipo, content_disposition_type="inline", filename=caminho.name)
