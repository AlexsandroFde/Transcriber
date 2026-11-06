"""Rotas dos participantes (nomes) e da exportação."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body

from ...servicos.contratos import ListaParticipantes, PedidoExportacao, PedidoNomes, ResultadoExportacao, ResultadoNomes
from ..dependencias import ServicosDep
from ..erros import respostas
from .transcricoes import IdTranscricao

rotas = APIRouter(prefix="/transcricoes/{id}")

_EXEMPLOS_NOMES = {
    "nomes": {"summary": "Dar nomes", "value": {"atribuicoes": [
        {"participante": "Participante 1", "nome": "Mariana"}, {"participante": "Participante 2", "nome": "Roberto"}]}},
    "unir": {"summary": "Unir dois rótulos da mesma pessoa",
             "description": "O Participante 5 passa a ser exibido com o nome do Participante 4.",
             "value": {"atribuicoes": [{"participante": "Participante 5", "nome": "Participante 4"}]}},
    "remover": {"summary": "Remover um nome", "value": {"atribuicoes": [{"participante": "Participante 3", "nome": ""}]}},
    "limpar": {"summary": "Remover todos os nomes", "value": {"limpar": True}},
}


@rotas.get("/participantes", response_model=ListaParticipantes, tags=["Participantes"],
           summary="Participantes e sugestões de nomes", responses=respostas(404, 422),
           description="Para cada participante, na ordem dos rótulos: tempo de fala, até 3 exemplos do que a pessoa "
                       "disse (frases com 4 palavras ou mais) e os nomes mencionados na conversa que apontam para ela "
                       "(autoidentificação, como \"aqui é a Ana\", ou alguém se dirigindo a ela pelo nome). "
                       "**Nenhuma sugestão é aplicada automaticamente.** `unido_com` lista os rótulos exibidos com o "
                       "mesmo nome.")
def listar(id: IdTranscricao, servicos: ServicosDep) -> ListaParticipantes:
    return servicos.transcricoes.participantes(id)


@rotas.patch("/participantes", response_model=ResultadoNomes, tags=["Participantes"],
             summary="Atribuir nomes aos participantes", responses=respostas(404, 409, 422),
             description="Aplica os nomes e **gera de novo todos os arquivos** (DOCX, MD, TXT, SRT, VTT, JSON e "
                         "relatório) na pasta da transcrição.\n\n"
                         "* O participante é indicado pelo rótulo (`Participante 1`) ou pela chave (`SPEAKER_00`).\n"
                         "* Nome vazio remove o nome; `limpar=true` remove todos antes de aplicar.\n"
                         "* Se o nome for o rótulo de outro participante, os dois são unidos (a mesma pessoa "
                         "detectada com dois rótulos). As uniões são aplicadas depois dos nomes diretos, então a "
                         "ordem das atribuições não muda o resultado.\n\n"
                         "Responde **409** se a transcrição estiver sendo processada de novo neste momento.")
def nomear(id: IdTranscricao, pedido: Annotated[PedidoNomes, Body(openapi_examples=_EXEMPLOS_NOMES)],
           servicos: ServicosDep) -> ResultadoNomes:
    return servicos.transcricoes.nomear(id, pedido)


@rotas.post("/exportacoes", response_model=ResultadoExportacao, tags=["Exportação"],
            summary="Gerar os arquivos de novo", responses=respostas(404, 409, 422),
            description="Gera os formatos pedidos a partir do JSON da transcrição, na pasta da transcrição ou em "
                        "`pasta_destino`. O JSON e o relatório de conferência são sempre gerados junto. Útil depois "
                        "de editar o JSON ou para obter um formato que não foi escolhido na transcrição.",
            openapi_extra={"requestBody": {"content": {"application/json": {"examples": {
                "todos": {"summary": "Todos os formatos, na mesma pasta", "value": {}},
                "outra_pasta": {"summary": "Word e legendas em outra pasta",
                                "value": {"formatos": ["docx", "srt"], "pasta_destino": "C:\\Entregas"}}}}}}})
def exportar(id: IdTranscricao, servicos: ServicosDep, pedido: PedidoExportacao | None = None) -> ResultadoExportacao:
    return servicos.transcricoes.exportar(id, pedido or PedidoExportacao())
