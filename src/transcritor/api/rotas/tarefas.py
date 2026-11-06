"""Rotas das tarefas: acompanhamento, cancelamento, retomada, registro e remoção."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from ...erros import Conflito
from ...servicos.contratos import EstadoTarefa, ListaTarefas, RegistroTarefa, Tarefa, TipoTarefa
from ..dependencias import ServicosDep
from ..erros import respostas

rotas = APIRouter(prefix="/tarefas", tags=["Tarefas"])

IdTarefa = Annotated[str, Path(description="Identificador da tarefa.", examples=["3f9c2a1b7d4e"],
                               pattern=r"^[0-9a-f]{12}$")]


@rotas.get("", response_model=ListaTarefas, summary="Listar tarefas",
           description="Tarefas da mais recente para a mais antiga, com o progresso de cada uma. Filtre por `tipo` e "
                       "por `estado` (pode repetir o parâmetro: `?estado=na_fila&estado=em_andamento`).")
def listar(servicos: ServicosDep, tipo: TipoTarefa | None = None,
           estado: Annotated[list[EstadoTarefa] | None, Query()] = None,
           limite: Annotated[int, Query(ge=1, le=500)] = 100) -> ListaTarefas:
    itens = servicos.tarefas.listar(tipo=tipo, estados=list(estado) if estado else None)
    return ListaTarefas(itens=itens[:limite], total=len(itens))


@rotas.get("/{id}", response_model=Tarefa, summary="Estado e progresso de uma tarefa", responses=respostas(404),
           description="Consulte periodicamente (por exemplo, a cada 2 segundos) ou use `GET /api/v1/eventos`.\n\n"
                       "* `progresso.percentual`: progresso geral ponderado pela duração típica das etapas;\n"
                       "* `progresso.etapas`: cada etapa com o estado (`pendente`, `em_andamento`, `concluida`, "
                       "`reaproveitada` do cache, `ignorada`, `falhou` ou `interrompida`);\n"
                       "* `progresso.fracao_etapa`: `null` quando a etapa não tem como medir o avanço (carregando um "
                       "modelo, por exemplo);\n"
                       "* `resultado` (quando `concluida`) e `erro` (quando `falhou` ou `interrompida`).")
def obter(id: IdTarefa, servicos: ServicosDep) -> Tarefa:
    return servicos.tarefas.obter(id)


@rotas.post("/{id}/cancelar", response_model=Tarefa, summary="Cancelar uma tarefa", responses=respostas(404, 409),
            description="Na fila: sai da fila. Em andamento: o processamento é interrompido imediatamente (o processo "
                        "é encerrado). As etapas de transcrição já concluídas ficam guardadas e serão reaproveitadas "
                        "se a mesma gravação for transcrita de novo. Responde **409** se a tarefa já terminou.")
def cancelar(id: IdTarefa, servicos: ServicosDep) -> Tarefa:
    return servicos.tarefas.cancelar(id)


@rotas.post("/{id}/repetir", response_model=Tarefa, status_code=status.HTTP_202_ACCEPTED,
            summary="Retomar ou repetir uma tarefa", responses=respostas(404, 409, 422),
            description="Cria uma tarefa nova com os mesmos parâmetros (`origem_id` aponta para a original). Para "
                        "transcrições interrompidas, canceladas ou com falha, isso retoma o trabalho: as etapas já "
                        "concluídas são reaproveitadas. O token do Hugging Face informado só para a tarefa original não "
                        "é guardado; vale o token salvo em Configurações.")
def repetir(id: IdTarefa, servicos: ServicosDep, response: Response) -> Tarefa:
    atual = servicos.tarefas.obter(id)
    if not atual.pode_repetir:
        raise Conflito("A tarefa ainda está na fila ou em andamento.", codigo="tarefa_ativa",
                       dica="Aguarde o fim da tarefa ou cancele-a antes de repetir.")
    if atual.tipo == "transcricao":
        nova = servicos.transcricoes.repetir(id)
    elif atual.tipo == "verificacao":
        nova, _ = servicos.diagnostico.verificar(atual.parametros.get("modelo") or "large-v3")
    else:
        nova, _ = servicos.diagnostico.baixar_modelos(atual.parametros.get("modelo") or "large-v3")
    response.headers["Location"] = f"/api/v1/tarefas/{nova.id}"
    return nova


@rotas.get("/{id}/registro", response_model=RegistroTarefa, summary="Registro técnico (log) da tarefa",
           responses=respostas(404),
           description="Linhas do registro técnico, a partir da linha `desde`. Para acompanhar sem repetir linhas, "
                       "passe em `desde` o valor de `proxima` da resposta anterior.")
def registro(id: IdTarefa, servicos: ServicosDep, desde: Annotated[int, Query(ge=0)] = 0) -> RegistroTarefa:
    return servicos.tarefas.ler_log(id, desde)


@rotas.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remover do histórico de tarefas",
              responses=respostas(404, 409),
              description="Remove uma tarefa encerrada e o registro dela. Não apaga transcrições nem arquivos. "
                          "Responde **409** para tarefas na fila ou em andamento (cancele antes).")
def remover(id: IdTarefa, servicos: ServicosDep) -> Response:
    servicos.tarefas.remover(id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
