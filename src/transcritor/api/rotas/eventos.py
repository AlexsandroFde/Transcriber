"""Notificações em tempo real (Server-Sent Events)."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ... import __version__
from ..dependencias import ServicosDep

rotas = APIRouter(tags=["Eventos"])

INTERVALO_PING_S = 15.0


def _sse(tipo: str, dados: dict) -> str:
    return f"event: {tipo}\ndata: {json.dumps(dados, ensure_ascii=False, default=str)}\n\n"


@rotas.get(
    "/eventos", summary="Eventos em tempo real (SSE)", response_class=StreamingResponse,
    responses={200: {"description": "Fluxo `text/event-stream` contínuo.", "content": {"text/event-stream": {
        "example": "event: tarefa\ndata: {\"tipo\": \"tarefa\", \"dados\": {\"id\": \"3f9c2a1b7d4e\", "
                   "\"estado\": \"em_andamento\", ...}, \"momento\": \"2026-11-05T14:02:11-03:00\"}\n\n"}}}},
    description="Mantém a conexão aberta e envia um evento a cada mudança. Cada mensagem tem `event: <tipo>` e "
                "`data:` com `{\"tipo\", \"dados\", \"momento\"}`. Tipos:\n\n"
                "| Tipo | `dados` |\n|---|---|\n"
                "| `conectado` | Saúde do serviço (enviado ao conectar). |\n"
                "| `tarefa` | A tarefa completa, igual a `GET /api/v1/tarefas/{id}` (no máximo 4 por segundo por "
                "tarefa; mudanças de estado e de etapa sempre são enviadas). |\n"
                "| `tarefa_removida` | `{\"id\"}` |\n"
                "| `log` | `{\"tarefa_id\", \"numero\", \"linha\"}`: nova linha do registro técnico. |\n"
                "| `transcricao` | `{\"id\", \"acao\"}` com `registrada`, `atualizada` ou `removida`. |\n"
                "| `ambiente` | `{\"situacao\"}`: a verificação do ambiente começou ou terminou. |\n"
                "| `ativacao` | `{\"arquivos\"}`: o aplicativo foi aberto de novo, possivelmente com arquivos. |\n\n"
                "Um comentário (`: ping`) é enviado a cada 15 segundos para manter a conexão. Ao reconectar, "
                "releia o estado pela API: eventos perdidos durante a desconexão não são reenviados.")
async def eventos(servicos: ServicosDep) -> StreamingResponse:
    assinatura = servicos.barramento.assinar(asyncio.get_running_loop())
    saude = {"versao": __version__, "tarefas_ativas": len(servicos.tarefas.ativas())}

    async def gerar():
        try:
            yield "retry: 3000\n\n"
            yield _sse("conectado", {"tipo": "conectado", "dados": saude})
            while True:
                try:
                    evento = await asyncio.wait_for(assinatura.fila.get(), timeout=INTERVALO_PING_S)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if evento.get("tipo") == "_fim":
                    break
                yield _sse(evento["tipo"], evento)
        finally:
            servicos.barramento.cancelar(assinatura)

    return StreamingResponse(gerar(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
