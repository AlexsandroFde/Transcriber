"""Rotas do ambiente: diagnóstico e download antecipado dos modelos."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from ...servicos.contratos import EstadoAmbiente, PedidoModelo, Tarefa
from ..dependencias import ServicosDep
from ..erros import respostas

rotas = APIRouter(prefix="/ambiente", tags=["Ambiente"])


@rotas.get("", response_model=EstadoAmbiente, summary="Situação do ambiente",
           description="Último relatório da verificação do ambiente: ffmpeg, placa de vídeo (CUDA), token do Hugging "
                       "Face (e acesso ao modelo community-1) e se os modelos de IA já foram baixados. A verificação "
                       "roda sozinha quando o serviço inicia; `situacao` indica `verificando` enquanto ela não termina.")
def estado(servicos: ServicosDep) -> EstadoAmbiente:
    return servicos.diagnostico.estado()


@rotas.post("/verificacoes", response_model=Tarefa, status_code=status.HTTP_202_ACCEPTED,
            summary="Verificar o ambiente de novo", responses=respostas(422, 503),
            description="Inicia uma verificação (tarefa do tipo `verificacao`, alguns segundos). Se já houver uma em "
                        "andamento, devolve essa mesma tarefa. O resultado fica em `GET /api/v1/ambiente` e no "
                        "`resultado` da tarefa. Equivale a `transcritor verificar`.")
def verificar(servicos: ServicosDep, response: Response, pedido: PedidoModelo | None = None) -> Tarefa:
    tarefa, _ = servicos.diagnostico.verificar((pedido or PedidoModelo()).modelo)
    response.headers["Location"] = f"/api/v1/tarefas/{tarefa.id}"
    return tarefa


@rotas.post("/modelos/downloads", response_model=Tarefa, status_code=status.HTTP_202_ACCEPTED,
            summary="Baixar os modelos agora", responses=respostas(422, 503),
            description="Baixa (ou confere) o modelo de reconhecimento, os modelos de identificação de participantes e, "
                        "com token, o modelo community-1, para que a primeira transcrição não precise esperar o "
                        "download (cerca de 3 GB). Tarefa do tipo `download_modelos`, com uma etapa por modelo. "
                        "Equivale a `transcritor verificar --baixar-modelos`.")
def baixar(servicos: ServicosDep, response: Response, pedido: PedidoModelo | None = None) -> Tarefa:
    tarefa, _ = servicos.diagnostico.baixar_modelos((pedido or PedidoModelo()).modelo)
    response.headers["Location"] = f"/api/v1/tarefas/{tarefa.id}"
    return tarefa
