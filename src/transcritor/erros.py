"""Erros da aplicação e tradução de falhas técnicas em mensagens compreensíveis.

As camadas de serviço lançam subclasses de ``ErroTranscritor``. A API converte cada
categoria em um código HTTP (ver ``transcritor.api.erros``) e a interface mostra
``mensagem`` e ``dica`` diretamente ao usuário. Por isso as mensagens são escritas para
quem não conhece o funcionamento interno do programa.

``descrever_excecao`` é usado pelo processo trabalhador para transformar exceções das
bibliotecas (ffmpeg, CUDA, Hugging Face...) em um ``DescricaoErro`` com o mesmo formato.
"""

from __future__ import annotations

import errno
import traceback
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ErroCampo:
    campo: str
    mensagem: str


class ErroTranscritor(Exception):
    """Base dos erros previstos. `codigo` é estável e pode ser usado por integrações."""

    codigo_padrao = "erro_interno"

    def __init__(self, mensagem: str, *, dica: str | None = None, codigo: str | None = None,
                 campos: list[ErroCampo] | None = None):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.dica = dica
        self.codigo = codigo or self.codigo_padrao
        self.campos = campos or []


class EntradaInvalida(ErroTranscritor):
    """Parâmetros válidos no formato, mas impossíveis de atender (arquivo inexistente etc.)."""

    codigo_padrao = "entrada_invalida"


class NaoEncontrado(ErroTranscritor):
    codigo_padrao = "nao_encontrado"


class Conflito(ErroTranscritor):
    """A operação conflita com o estado atual (tarefa já encerrada, pasta em uso...)."""

    codigo_padrao = "conflito"


class Indisponivel(ErroTranscritor):
    """O serviço não consegue atender agora (encerrando, recurso do sistema ausente)."""

    codigo_padrao = "indisponivel"


@dataclass
class DescricaoErro:
    codigo: str
    mensagem: str
    dica: str | None = None
    detalhe: str | None = None  # texto técnico (vai para o registro, não para a tela)
    extras: dict[str, Any] = field(default_factory=dict)

    def para_dict(self) -> dict[str, Any]:
        return asdict(self)


_DICA_LOG = "Os detalhes técnicos estão no registro (log) da tarefa."


def _texto(exc: BaseException) -> str:
    return str(exc).strip() or exc.__class__.__name__


def _primeira_linha(texto: str, limite: int = 400) -> str:
    linha = texto.strip().splitlines()[0] if texto.strip() else texto
    return linha if len(linha) <= limite else linha[: limite - 3] + "..."


def descrever_excecao(exc: BaseException) -> DescricaoErro:
    """Converte uma exceção qualquer em mensagem para o usuário, com dica de solução."""
    detalhe = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if isinstance(exc, ErroTranscritor):
        return DescricaoErro(exc.codigo, exc.mensagem, exc.dica, detalhe)

    texto = _texto(exc)
    baixo = texto.lower()
    nome = f"{type(exc).__module__}.{type(exc).__name__}".lower()

    def d(codigo: str, mensagem: str, dica: str | None) -> DescricaoErro:
        return DescricaoErro(codigo, mensagem, dica, detalhe)

    if isinstance(exc, KeyboardInterrupt):
        return d("interrompido", "O processamento foi interrompido.",
                 "As etapas concluídas ficam guardadas e serão reaproveitadas ao retomar.")
    if isinstance(exc, FileNotFoundError):
        alvo = exc.filename or texto
        return d("arquivo_nao_encontrado", f"Arquivo não encontrado: {alvo}",
                 "Verifique se o arquivo foi movido, renomeado ou se o disco onde ele está continua conectado.")
    if isinstance(exc, PermissionError):
        alvo = exc.filename or ""
        return d("sem_permissao", f"Sem permissão para acessar {alvo}".strip(),
                 "Escolha outra pasta de saída ou feche programas que estejam usando o arquivo (por exemplo, o Word).")
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return d("disco_cheio", "Não há espaço livre suficiente no disco.",
                 "Libere espaço (a transcrição usa arquivos temporários do tamanho do áudio) ou escolha outra pasta de saída.")
    if isinstance(exc, MemoryError):
        return d("memoria_insuficiente", "Faltou memória no computador para concluir o processamento.",
                 "Feche outros programas e tente de novo. Em gravações muito longas, divida o arquivo em partes.")
    if "out of memory" in baixo or "outofmemory" in nome or "cuda_error_out_of_memory" in baixo:
        return d("memoria_gpu", "Faltou memória na placa de vídeo.",
                 "Em Opções avançadas, escolha a precisão int8_float16 ou o modelo large-v3-turbo, "
                 "e feche outros programas que usem a placa de vídeo.")
    if "não possui faixa de áudio" in baixo:
        return d("sem_audio", "O arquivo não possui faixa de áudio.",
                 "Escolha um vídeo ou áudio que tenha som gravado.")
    if "faixa de áudio" in baixo and "não existe" in baixo:
        return d("faixa_inexistente", _primeira_linha(texto),
                 "Em Opções avançadas, escolha uma das faixas de áudio disponíveis ou a opção de mixar todas.")
    if "falha no ffmpeg" in baixo or nome.startswith("av.") or "invaliddataerror" in nome:
        return d("midia_ilegivel", "Não foi possível ler o áudio deste arquivo.",
                 "O arquivo pode estar corrompido, incompleto (gravação interrompida) ou em um formato não suportado. "
                 "Tente convertê-lo para MP4 ou WAV.")
    if "gatedrepo" in nome or ("401" in baixo and "huggingface" in baixo) or "acesso negado ao modelo" in baixo:
        return d("acesso_negado_modelo", _primeira_linha(texto),
                 "Confira o token em Configurações e se os termos de uso do modelo foram aceitos com a mesma conta. "
                 "Na identificação de participantes, a opção Automática funciona sem token.")
    if nome.endswith("errodiarizacao"):
        return d("diarizacao_indisponivel", _primeira_linha(texto),
                 "Na identificação de participantes, use a opção Automática, que funciona sem token.")
    conexao = ("connection" in nome or "timeout" in nome or "urlerror" in nome or "offline" in nome
               or "localentrynotfound" in nome or "max retries" in baixo or "name resolution" in baixo
               or "getaddrinfo" in baixo or "connecterror" in nome)
    if conexao:
        return d("sem_conexao", "Não foi possível baixar os modelos de IA.",
                 "Verifique a conexão com a internet. Os modelos são baixados uma única vez (cerca de 3 GB).")
    if "cuda" in baixo or "cudnn" in baixo or "cublas" in baixo:
        return d("erro_gpu", "A placa de vídeo apresentou um erro durante o processamento.",
                 "Atualize o driver da NVIDIA. Se o problema continuar, escolha o dispositivo CPU em Opções avançadas.")
    if isinstance(exc, ValueError) and "não é um arquivo de transcrição" in baixo:
        return d("json_invalido", _primeira_linha(texto),
                 "Escolha o arquivo .json gerado pelo Transcritor (fica na pasta da transcrição).")
    return d("erro_inesperado", _primeira_linha(texto) or "Erro inesperado.", _DICA_LOG)
