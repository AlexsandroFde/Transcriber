"""Rotas de configuração: token do Hugging Face e glossário padrão."""

from __future__ import annotations

from fastapi import APIRouter

from ...servicos import glossario as glossario_mod
from ...servicos.contratos import (
    EstadoToken,
    Glossario,
    GlossarioInterpretado,
    PedidoGlossario,
    PedidoInterpretarGlossario,
    PedidoToken,
)
from ..dependencias import ServicosDep
from ..erros import respostas

rotas = APIRouter(prefix="/configuracao", tags=["Configuração"])


@rotas.get("/token-hf", response_model=EstadoToken, summary="Situação do token do Hugging Face",
           description="Se há um token, de onde ele vem (arquivo salvo pelo Transcritor, variável de ambiente ou login "
                       "do Hugging Face) e os 4 últimos caracteres. **O token nunca é devolvido.** O token é opcional: "
                       "sem ele, a identificação de participantes usa o pipeline pyannote 3.1 de acesso livre.")
def estado_token(servicos: ServicosDep) -> EstadoToken:
    return servicos.configuracao.estado_token()


@rotas.put("/token-hf", response_model=EstadoToken, summary="Salvar o token do Hugging Face",
           responses=respostas(422),
           description="Guarda o token para usar o modelo pyannote community-1. Antes, crie uma conta no Hugging Face, "
                       "aceite os termos do modelo (`pagina_modelo`) e gere um token de leitura (`pagina_tokens`). "
                       "Depois, verifique o acesso com `POST /api/v1/ambiente/verificacoes`. Equivale a "
                       "`transcritor configurar-token`.")
def salvar_token(pedido: PedidoToken, servicos: ServicosDep) -> EstadoToken:
    return servicos.configuracao.salvar_token(pedido.token.get_secret_value())


@rotas.delete("/token-hf", response_model=EstadoToken, summary="Remover o token salvo", responses=respostas(409),
              description="Apaga o token salvo pelo Transcritor. Responde **409** quando o token vem de uma variável de "
                          "ambiente ou do login do Hugging Face, que precisam ser removidos fora do programa.")
def remover_token(servicos: ServicosDep) -> EstadoToken:
    return servicos.configuracao.remover_token()


@rotas.get("/glossario", response_model=Glossario, summary="Glossário padrão",
           description="O glossário que a interface sugere em toda transcrição nova (o `glossario.txt` da pasta do "
                       "programa, quando existe, como no antigo `transcrever.bat`). `termos` mostra como o texto é "
                       "interpretado.")
def glossario(servicos: ServicosDep) -> Glossario:
    return servicos.configuracao.glossario()


@rotas.put("/glossario", response_model=Glossario, summary="Salvar o glossário padrão", responses=respostas(422),
           description="Formato: um termo por linha, vários separados por `;`, e o texto após `#` é ignorado.")
def salvar_glossario(pedido: PedidoGlossario, servicos: ServicosDep) -> Glossario:
    return servicos.configuracao.salvar_glossario(pedido.texto)


@rotas.post("/glossario/interpretar", response_model=GlossarioInterpretado, summary="Interpretar um glossário",
            responses=respostas(404, 422),
            description="Mostra os termos que serão usados a partir de um texto ou de um arquivo .txt (útil para "
                        "conferir um glossário antes de transcrever ou para importar um arquivo).")
def interpretar(pedido: PedidoInterpretarGlossario) -> GlossarioInterpretado:
    texto = pedido.texto if pedido.texto is not None else glossario_mod.ler_texto(pedido.caminho or "")
    return GlossarioInterpretado(termos=glossario_mod.interpretar(texto), texto=texto)
