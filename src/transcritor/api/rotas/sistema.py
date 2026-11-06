"""Rotas do sistema: saúde, informações, catálogo de opções e integração com o sistema operacional."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from ... import __version__
from ...erros import Conflito
from ...servicos import sistema
from ...servicos.catalogo import catalogo
from ...servicos.contratos import CatalogoOpcoes, InfoSistema, PedidoAbrir, PedidoAtivacao, Saude
from ..dependencias import ServicosDep
from ..erros import respostas

rotas = APIRouter(tags=["Sistema"])


@rotas.get("/saude", response_model=Saude, summary="Saúde do serviço",
           description="Responde assim que a API está pronta. O inicializador do aplicativo usa esta rota para saber "
                       "quando mostrar a interface.")
def saude(servicos: ServicosDep) -> Saude:
    return Saude(versao=__version__, modo=servicos.modo, iniciado_em=servicos.iniciado_em,
                 tarefas_ativas=len(servicos.tarefas.ativas()))


@rotas.get("/sistema", response_model=InfoSistema, summary="Informações gerais",
           description="Versão, plataforma e as pastas usadas pelo programa (configuração, dados, modelos, registros).")
def informacoes(servicos: ServicosDep) -> InfoSistema:
    return sistema.informacoes(servicos.config, servicos.modo)


@rotas.get("/opcoes", response_model=CatalogoOpcoes, summary="Catálogo das opções de transcrição",
           description="Valores aceitos por cada opção de `POST /api/v1/transcricoes`, com rótulo e explicação, os "
                       "valores padrão e os limites numéricos. A interface monta os campos a partir daqui.")
def opcoes() -> CatalogoOpcoes:
    return catalogo()


@rotas.post("/sistema/abrir", status_code=status.HTTP_204_NO_CONTENT, summary="Abrir um arquivo ou pasta",
            responses=respostas(403, 404, 422),
            description="Abre no programa padrão do sistema (Word, player de vídeo, Explorador de Arquivos). Com "
                        "`revelar=true`, mostra o arquivo selecionado na pasta. Por segurança, só abre pastas, mídias e "
                        "os tipos de arquivo gerados pelo Transcritor. Só faz sentido quando a API roda no mesmo "
                        "computador de quem a usa.")
def abrir(pedido: PedidoAbrir) -> Response:
    sistema.abrir(pedido.caminho, pedido.revelar)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@rotas.post("/sistema/ativar", status_code=status.HTTP_202_ACCEPTED, summary="Trazer o aplicativo para a frente",
            description="Usado pelo inicializador quando o Transcritor já está aberto: traz a janela para a frente e "
                        "entrega os arquivos recebidos (por exemplo, um vídeo arrastado sobre o atalho), que a "
                        "interface recebe pelo evento `ativacao`.")
def ativar(pedido: PedidoAtivacao, servicos: ServicosDep) -> Response:
    servicos.barramento.publicar("ativacao", {"arquivos": pedido.arquivos})
    return Response(status_code=status.HTTP_202_ACCEPTED)


@rotas.post("/sistema/encerrar", status_code=status.HTTP_202_ACCEPTED, summary="Encerrar o serviço",
            responses=respostas(409),
            description="Encerra o serviço (e o aplicativo, quando ele está aberto). Tarefas em andamento são "
                        "interrompidas e poderão ser retomadas depois. Responde **409** quando o serviço não foi "
                        "iniciado pelo aplicativo nem por `transcritor servidor`.")
def encerrar(request: Request) -> Response:
    ao_encerrar = getattr(request.app.state, "ao_encerrar", None)
    if ao_encerrar is None:
        raise Conflito("Este serviço não pode ser encerrado pela API.", codigo="encerramento_indisponivel")
    ao_encerrar()
    return Response(status_code=status.HTTP_202_ACCEPTED)
