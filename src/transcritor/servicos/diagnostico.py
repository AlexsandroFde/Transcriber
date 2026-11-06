"""Diagnóstico do ambiente (antes `transcritor verificar`) e download antecipado dos modelos.

`verificar` e `baixar_modelos` carregam torch, CUDA e o Hugging Face; por isso rodam no
processo trabalhador (ou diretamente na linha de comando). `ServicoDiagnostico` é a parte
do servidor: cria essas tarefas e guarda o último relatório.
"""

from __future__ import annotations

import logging
import platform
import sys
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .. import __version__
from .contratos import (
    EstadoAmbiente,
    EstadoFfmpeg,
    EstadoGpu,
    EstadoModelo,
    EstadoTokenAmbiente,
    RelatorioAmbiente,
    ResultadoDownload,
    Tarefa,
)

log = logging.getLogger("transcritor")

AVISO_SEM_GPU = ("Sem placa de vídeo compatível: a transcrição usará o processador e será cerca de 10 vezes mais "
                 "lenta. O modelo large-v3-turbo é mais rápido nesse caso.")
AVISO_MODELOS = "Os modelos de IA (cerca de 3 GB) ainda não foram baixados: isso acontece na primeira transcrição."


def _sem_conexao(e: BaseException) -> bool:
    nome = type(e).__name__.lower()
    texto = str(e).lower()
    return any(x in nome for x in ("connect", "timeout", "offline")) or "name resolution" in texto or \
        "getaddrinfo" in texto or "max retries" in texto


def verificar_acesso_pyannote(token: str) -> tuple[str, str]:
    """('ok' | 'negado' | 'erro', mensagem) para o modelo pyannote community-1."""
    from ..processamento.diarizacao import MODELO_PYANNOTE, PAGINA_MODELO

    try:
        from huggingface_hub import HfApi, hf_hub_download
    except Exception as e:  # pragma: no cover - dependência ausente
        return "erro", f"Não foi possível verificar o acesso ao Hugging Face: {e}"
    try:
        HfApi().model_info(MODELO_PYANNOTE, token=token, files_metadata=False)
        hf_hub_download(MODELO_PYANNOTE, "config.yaml", token=token)
        return "ok", f"Acesso ao modelo de diarização {MODELO_PYANNOTE}: ok"
    except Exception as e:
        primeira = (str(e).strip().splitlines() or [type(e).__name__])[0]
        if _sem_conexao(e):
            return "erro", f"Sem conexão para verificar o acesso a {MODELO_PYANNOTE}: {primeira}"
        return "negado", (f"Sem acesso a {MODELO_PYANNOTE}: {primeira}\n"
                          f"  Aceite os termos em {PAGINA_MODELO} com a mesma conta do token.")


def _em_cache(repo: str, arquivo: str) -> bool | None:
    try:
        from huggingface_hub import try_to_load_from_cache

        return isinstance(try_to_load_from_cache(repo, arquivo), str)
    except Exception:
        return None


def estado_modelo_asr(modelo: str) -> EstadoModelo:
    nome = f"Whisper {modelo}"
    descricao = "Reconhecimento de fala (cerca de 3 GB)."
    if Path(modelo).is_dir():
        return EstadoModelo(id="reconhecimento", nome=nome, descricao="Modelo local.", baixado=True)
    try:
        from faster_whisper.utils import download_model

        download_model(modelo, local_files_only=True)
        baixado: bool | None = True
    except ValueError:
        baixado, descricao = None, "Nome de modelo não reconhecido pelo faster-whisper."
    except Exception:
        baixado = False
    return EstadoModelo(id="reconhecimento", nome=nome, descricao=descricao, baixado=baixado)


def estado_modelos(modelo: str, token: str | None) -> list[EstadoModelo]:
    from ..ambiente import pasta_modelos
    from ..processamento.diarizacao import EMBEDDING_LIVRE, MODELO_PYANNOTE, URL_EMBEDDING

    sherpa = pasta_modelos() / "sherpa"
    seg = (sherpa / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx").is_file()
    titanet = (sherpa / URL_EMBEDDING.rsplit("/", 1)[-1]).is_file()
    wespeaker = _em_cache(EMBEDDING_LIVRE, "pytorch_model.bin")
    livre = None if wespeaker is None else (seg and titanet and wespeaker)
    modelos = [estado_modelo_asr(modelo),
               EstadoModelo(id="diarizacao", nome="Identificação de participantes",
                            descricao="Segmentação pyannote 3.0 e WeSpeaker (acesso livre, cerca de 30 MB).",
                            baixado=livre)]
    if token:
        modelos.append(EstadoModelo(id="pyannote", nome="pyannote community-1",
                                    descricao="Modelo mais recente de identificação de participantes (com token).",
                                    baixado=_em_cache(MODELO_PYANNOTE, "config.yaml"), obrigatorio=False))
    return modelos


def verificar(modelo: str = "large-v3") -> RelatorioAmbiente:
    from ..ambiente import caminho_ffmpeg, cuda_disponivel, descrever_gpu, localizar_token

    try:
        ffmpeg = EstadoFfmpeg(disponivel=True, caminho=caminho_ffmpeg())
    except Exception as e:
        ffmpeg = EstadoFfmpeg(disponivel=False, mensagem=f"ffmpeg não encontrado ({e})")
    if cuda_disponivel():
        gpu = EstadoGpu(disponivel=True, descricao=descrever_gpu())
    else:
        gpu = EstadoGpu(disponivel=False, descricao="nenhuma (CPU)",
                        mensagem="indisponível; o processamento usará a CPU (bem mais lento)")
    token, origem = localizar_token()
    if token:
        acesso, msg = verificar_acesso_pyannote(token)
        estado_token = EstadoTokenAmbiente(configurado=True, origem=origem, acesso_modelo=acesso, mensagem=msg)
    else:
        estado_token = EstadoTokenAmbiente(
            configurado=False, acesso_modelo="sem_token",
            mensagem="Opcional. Sem token, a identificação de participantes usa o pipeline pyannote 3.1 de acesso "
                     "livre.")
    modelos = estado_modelos(modelo, token)
    avisos = []
    if not ffmpeg.disponivel:
        avisos.append("O ffmpeg não foi encontrado: reinstale o Transcritor (instalar.bat).")
    if not gpu.disponivel:
        avisos.append(AVISO_SEM_GPU)
    if estado_token.acesso_modelo == "negado":
        avisos.append("O token do Hugging Face não dá acesso ao modelo community-1; será usado o pipeline livre.")
    if any(m.obrigatorio and m.baixado is False for m in modelos):
        avisos.append(AVISO_MODELOS)
    return RelatorioAmbiente(versao=__version__, python=sys.version.split()[0], plataforma=platform.platform(),
                             ffmpeg=ffmpeg, gpu=gpu, token_hf=estado_token, modelos=modelos, pronto=ffmpeg.disponivel,
                             avisos=avisos, verificado_em=datetime.now().astimezone())


Etapa = Callable[[int, str, str], None]  # (número, texto, situação)


def baixar_modelos(modelo: str = "large-v3", etapa: Etapa | None = None) -> ResultadoDownload:
    """Baixa (ou confere) os modelos agora, para não haver espera na primeira transcrição."""
    from ..ambiente import token_hf

    etapa = etapa or (lambda n, texto, situacao: log.info(texto))
    mensagens: list[str] = []

    def informar(texto: str) -> None:
        log.info(texto)
        mensagens.append(texto)

    etapa(1, f"Baixando/verificando o modelo de reconhecimento {modelo}...", "executando")
    from ..processamento.asr import Reconhecedor

    rec = Reconhecedor(modelo)
    informar(f"Modelo {modelo} pronto ({rec.dispositivo}, {rec.precisao}).")
    rec.liberar()

    etapa(2, "Baixando/verificando os modelos de diarização...", "executando")
    from ..processamento.diarizacao import MODELO_PYANNOTE, modelos_livre

    modelos_livre()
    informar("Modelos de identificação de participantes prontos.")

    token = token_hf()
    if token:
        etapa(3, f"Baixando/verificando o modelo {MODELO_PYANNOTE}...", "executando")
        from ..ambiente import carregar_torch

        carregar_torch()
        from pyannote.audio import Pipeline

        if Pipeline.from_pretrained(MODELO_PYANNOTE, token=token) is not None:
            informar(f"Modelo {MODELO_PYANNOTE} pronto.")
        else:
            informar(f"Sem acesso ao modelo {MODELO_PYANNOTE}; será usado o pipeline livre.")
    else:
        etapa(3, "Modelo community-1: sem token do Hugging Face (opcional)", "ignorada")
    return ResultadoDownload(modelos=estado_modelos(modelo, token), mensagens=mensagens)


class ServicoDiagnostico:
    """Lado do servidor: cria as tarefas de verificação/download e guarda o último relatório."""

    def __init__(self, tarefas, barramento) -> None:
        self.tarefas = tarefas
        self.barramento = barramento
        self._relatorio: RelatorioAmbiente | None = None
        self._lock = threading.Lock()
        tarefas.ao_concluir("verificacao", self._ao_verificar)
        tarefas.ao_concluir("download_modelos", self._ao_baixar)

    def _ao_verificar(self, _tarefa, resultado: dict) -> dict:
        with self._lock:
            self._relatorio = RelatorioAmbiente.model_validate(resultado)
        self.barramento.publicar("ambiente", {"situacao": "verificado"})
        return resultado

    def _ao_baixar(self, _tarefa, resultado: dict) -> dict:
        with self._lock:
            if self._relatorio is not None:
                self._relatorio = self._relatorio.model_copy(
                    update={"modelos": ResultadoDownload.model_validate(resultado).modelos,
                            "avisos": [a for a in self._relatorio.avisos if a != AVISO_MODELOS]})
        self.barramento.publicar("ambiente", {"situacao": "verificado"})
        return resultado

    def _ativa(self, tipo: str) -> Tarefa | None:
        ativas = self.tarefas.ativas(tipo)
        return ativas[0] if ativas else None

    def estado(self) -> EstadoAmbiente:
        ativa = self._ativa("verificacao")
        with self._lock:
            relatorio = self._relatorio
        if ativa is not None:
            return EstadoAmbiente(situacao="verificando", relatorio=relatorio, tarefa_id=ativa.id)
        return EstadoAmbiente(situacao="verificado" if relatorio else "nao_verificado", relatorio=relatorio)

    def verificar(self, modelo: str = "large-v3") -> tuple[Tarefa, bool]:
        """Inicia uma verificação (ou devolve a que já está em andamento). (tarefa, criada)."""
        ativa = self._ativa("verificacao")
        if ativa is not None:
            return ativa, False
        self.barramento.publicar("ambiente", {"situacao": "verificando"})
        return self.tarefas.criar("verificacao", "Verificação do ambiente", {"modelo": modelo}), True

    def baixar_modelos(self, modelo: str = "large-v3") -> tuple[Tarefa, bool]:
        ativa = self._ativa("download_modelos")
        if ativa is not None:
            return ativa, False
        return self.tarefas.criar("download_modelos", "Download dos modelos de IA", {"modelo": modelo}), True
