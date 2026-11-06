"""Textos da documentação OpenAPI e a página /docs (Swagger UI servido localmente, sem internet)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse

from ..config import PREFIXO_API

TITULO = "Transcritor de reuniões: API"

DESCRICAO = f"""
API REST do **Transcritor**, que transcreve gravações de reuniões em português brasileiro com
identificação de participantes, marcação de tempo e sinalização do que não foi compreendido com
segurança. Tudo roda neste computador: nenhum áudio é enviado para fora.

A interface gráfica do Transcritor usa exclusivamente esta API; qualquer outro programa pode fazer o mesmo.

## Como uma transcrição acontece

Transcrever leva minutos (de um quinto a um terço da duração da gravação, com placa de vídeo), por isso o
processamento é **assíncrono**:

1. `POST {PREFIXO_API}/transcricoes` com os caminhos dos arquivos e as opções. A resposta chega na hora
   (**202 Accepted**) com uma tarefa por arquivo, no estado `na_fila`. Erros simples (arquivo inexistente,
   faixa de áudio que não existe) são recusados já nesta chamada, com **422**.
2. Acompanhe cada tarefa de uma destas formas:
   * consultando `GET {PREFIXO_API}/tarefas/{{id}}` (por exemplo, a cada 2 segundos); ou
   * assinando `GET {PREFIXO_API}/eventos` (Server-Sent Events), que envia cada mudança de estado e de
     progresso no instante em que ela acontece.
3. O progresso traz o percentual geral, as seis etapas (extração, tratamento do áudio, identificação dos
   participantes, transcrição, revisão e montagem), a mensagem atual e a estimativa de tempo restante.
4. Quando `estado` vira `concluida`, `resultado.transcricao_id` identifica a transcrição: use
   `GET {PREFIXO_API}/transcricoes/{{id}}` para os detalhes, `/conteudo` para o texto, `/relatorio` para os
   pontos de conferência e `/arquivos/{{tipo}}` para baixar DOCX, MD, TXT, SRT, VTT ou JSON.
5. Se der errado, `estado` vira `falhou` e `erro` explica o motivo e como resolver.

Estados de uma tarefa: `na_fila` → `em_andamento` → `concluida` | `falhou` | `cancelada`. Tarefas que estavam em
andamento quando o programa foi fechado aparecem como `interrompida`: `POST {PREFIXO_API}/tarefas/{{id}}/repetir`
retoma a transcrição, reaproveitando as etapas que já tinham terminado.

As transcrições rodam uma de cada vez (elas disputam a placa de vídeo). Verificações do ambiente e downloads de
modelos rodam em paralelo a elas.

## Erros

Toda resposta de erro tem o mesmo formato, com um `codigo` estável para integrações e uma `mensagem` e uma `dica`
escritas para quem usa o programa:

```json
{{"erro": {{"codigo": "arquivo_nao_encontrado", "status": 422,
           "mensagem": "Arquivo não encontrado: C:\\\\Videos\\\\reuniao.mp4",
           "dica": "Verifique se o arquivo foi movido, renomeado ou se o disco continua conectado.",
           "campos": [{{"campo": "arquivos[0]", "mensagem": "Arquivo não encontrado: ..."}}]}}}}
```

| Código HTTP | Quando |
|---|---|
| 200, 201 | Operação concluída (201: recurso criado). |
| 202 | Tarefa aceita; acompanhe pelo `id`. |
| 204 | Concluído, sem conteúdo de resposta. |
| 400 | Nome de host não permitido. |
| 403 | Pedido vindo de outro site aberto no navegador. |
| 404 | Recurso não encontrado. |
| 409 | Conflito com o estado atual (por exemplo, cancelar uma tarefa já concluída). |
| 422 | Dados inválidos; `campos` indica cada problema. |
| 500 | Erro inesperado (os detalhes ficam no registro do aplicativo). |
| 503 | O serviço está sendo encerrado. |

## Arquivos e caminhos

A API roda no mesmo computador que os arquivos: os pedidos usam **caminhos locais** (por exemplo,
`C:\\\\Users\\\\ana\\\\Videos\\\\reuniao.mp4`). Programas que não têm acesso ao disco podem enviar a gravação por
`POST {PREFIXO_API}/midia/envios` e usar o `caminho` devolvido.

## Segurança

Por padrão a API só atende este computador (`127.0.0.1`). Pedidos feitos por outros sites abertos no navegador
são recusados. Não há autenticação: não exponha a API na rede sem uma camada de proteção própria.

## Exemplo com curl

```bash
curl -X POST http://127.0.0.1:8765{PREFIXO_API}/transcricoes \\
     -H "Content-Type: application/json" \\
     -d '{{"arquivos": ["C:/Videos/reuniao.mp4"], "participantes": 4}}'
curl http://127.0.0.1:8765{PREFIXO_API}/tarefas/ID_DA_TAREFA
```
"""

TAGS = [
    {"name": "Transcrições", "description": "Criar transcrições (assíncronas) e consultar as concluídas: detalhes, "
                                            "texto, relatório de conferência, arquivos e a gravação original."},
    {"name": "Tarefas", "description": "Acompanhar, cancelar, retomar e remover as tarefas demoradas "
                                       "(transcrições, verificações do ambiente e downloads de modelos)."},
    {"name": "Eventos", "description": "Notificações em tempo real (Server-Sent Events)."},
    {"name": "Participantes", "description": "Identificar os participantes: exemplos de fala, nomes sugeridos e "
                                             "atribuição de nomes (o programa nunca atribui nomes sozinho)."},
    {"name": "Exportação", "description": "Gerar de novo os arquivos de saída a partir do JSON da transcrição."},
    {"name": "Mídia", "description": "Inspecionar gravações (duração e faixas de áudio) e enviar arquivos."},
    {"name": "Ambiente", "description": "Verificar placa de vídeo, ffmpeg, modelos e token, e baixar os modelos."},
    {"name": "Configuração", "description": "Token do Hugging Face e glossário padrão."},
    {"name": "Sistema", "description": "Saúde do serviço, informações gerais, catálogo de opções e integração com "
                                       "o sistema operacional."},
]


def registrar(app: FastAPI) -> None:
    @app.get("/docs", include_in_schema=False)
    def documentacao() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=app.openapi_url or f"{PREFIXO_API}/openapi.json",
            title=TITULO,
            swagger_js_url="/vendor/swagger-ui/swagger-ui-bundle.js",
            swagger_css_url="/vendor/swagger-ui/swagger-ui.css",
            swagger_favicon_url="/favicon.svg",
            swagger_ui_parameters={"docExpansion": "list", "defaultModelsExpandDepth": 0, "filter": True,
                                   "displayRequestDuration": True, "tryItOutEnabled": True,
                                   "persistAuthorization": False, "syntaxHighlight": {"theme": "agate"}},
        )
