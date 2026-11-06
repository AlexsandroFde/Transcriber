"""Arquivos de mídia: inspeção (duração, faixas de áudio) e envio pela API.

O envio (`POST /api/v1/midia/envios`) existe para integrações que não compartilham o disco
com o Transcritor: o arquivo é gravado em `<pasta de dados>/envios/<id>/` e o caminho
devolvido é usado ao criar a transcrição, como qualquer outro.
"""

from __future__ import annotations

import logging
import re
import shutil
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from ..config import Configuracoes
from ..erros import Conflito, EntradaInvalida, NaoEncontrado
from ..processamento.pipeline import pasta_de_saida
from .contratos import ArquivoEnviado, FaixaAudio, InfoMidia

log = logging.getLogger("transcritor.midia")


def resolver_arquivo(caminho: str, campo: str | None = None) -> Path:
    """Caminho absoluto de um arquivo existente (erro compreensível se não existir)."""
    arq = Path(caminho.strip().strip('"')).expanduser()
    try:
        arq = arq.resolve()
    except OSError:
        pass
    if not arq.exists():
        raise NaoEncontrado(f"Arquivo não encontrado: {arq}", codigo="arquivo_nao_encontrado",
                            dica="Verifique se o arquivo foi movido, renomeado ou se o disco continua conectado.")
    if arq.is_dir():
        raise EntradaInvalida(f"O caminho indica uma pasta, não um arquivo: {arq}", codigo="caminho_e_pasta",
                              dica="Escolha o arquivo de vídeo ou de áudio dentro da pasta.")
    return arq


def informacoes(caminho: str, pasta_saida: str | None = None) -> InfoMidia:
    from ..processamento.audio import sondar

    arq = resolver_arquivo(caminho)
    try:
        info = sondar(arq)
    except Exception as e:
        log.info("Não foi possível ler %s como mídia: %s", arq, e)
        raise EntradaInvalida(f"Não foi possível ler {arq.name} como vídeo ou áudio.", codigo="midia_invalida",
                              dica="O arquivo pode estar corrompido ou em um formato não suportado. "
                                   "Tente convertê-lo para MP4 ou WAV.") from e
    faixas = [FaixaAudio(indice=f["indice_audio"], canais=f["canais"], taxa_hz=f["taxa"], codec=f.get("codec"),
                         idioma=f.get("idioma"), titulo=f.get("titulo")) for f in info.faixas_audio]
    saida = Path(pasta_saida).expanduser() if pasta_saida else None
    return InfoMidia(caminho=str(arq), nome=arq.name, tamanho_bytes=arq.stat().st_size, duracao_s=info.duracao,
                     tem_video=info.tem_video, faixas_audio=faixas,
                     pasta_saida_padrao=str(pasta_de_saida(arq, saida)))


def _nome_seguro(nome: str) -> str:
    nome = Path(nome.replace("\\", "/")).name.strip()
    nome = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", nome).strip(". ")
    return nome[:180] or "arquivo"


class ServicoEnvios:
    def __init__(self, config: Configuracoes):
        self.config = config

    @property
    def pasta(self) -> Path:
        return self.config.pasta_envios

    def salvar(self, nome_original: str, fluxo: BinaryIO) -> ArquivoEnviado:
        id_ = uuid.uuid4().hex[:12]
        destino_pasta = self.pasta / id_
        destino_pasta.mkdir(parents=True, exist_ok=True)
        destino = destino_pasta / _nome_seguro(nome_original)
        total = 0
        limite = self.config.tamanho_maximo_envio
        try:
            with open(destino, "wb") as f:
                while bloco := fluxo.read(1 << 20):
                    total += len(bloco)
                    if total > limite:
                        raise EntradaInvalida(
                            f"O arquivo passa do limite de {limite // 1024**3} GB para envio.",
                            codigo="arquivo_grande_demais",
                            dica="Use o caminho do arquivo no disco em vez de enviá-lo.")
                    f.write(bloco)
        except BaseException:
            shutil.rmtree(destino_pasta, ignore_errors=True)
            raise
        if total == 0:
            shutil.rmtree(destino_pasta, ignore_errors=True)
            raise EntradaInvalida("O arquivo enviado está vazio.", codigo="arquivo_vazio")
        log.info("Arquivo recebido: %s (%d bytes)", destino, total)
        return self._descrever(destino)

    def _descrever(self, arq: Path) -> ArquivoEnviado:
        st = arq.stat()
        return ArquivoEnviado(id=arq.parent.name, nome=arq.name, caminho=str(arq.resolve()), tamanho_bytes=st.st_size,
                              enviado_em=datetime.fromtimestamp(st.st_mtime).astimezone())

    def _arquivo(self, id_: str) -> Path | None:
        """O arquivo de mídia de um envio (ignora a pasta de resultados criada ao lado dele)."""
        if not re.fullmatch(r"[0-9a-f]{12}", id_):
            return None
        pasta = self.pasta / id_
        if not pasta.is_dir():
            return None
        arquivos = [p for p in pasta.iterdir() if p.is_file()]
        return arquivos[0] if arquivos else None

    def listar(self) -> list[ArquivoEnviado]:
        if not self.pasta.is_dir():
            return []
        itens = [self._descrever(a) for p in self.pasta.iterdir() if p.is_dir() and (a := self._arquivo(p.name))]
        itens.sort(key=lambda e: e.enviado_em, reverse=True)
        return itens

    def remover(self, id_: str, em_uso: Callable[[Path], bool] | None = None) -> None:
        """Apaga o arquivo enviado. Os resultados de transcrições feitas a partir dele são preservados."""
        arq = self._arquivo(id_)
        if arq is None:
            raise NaoEncontrado(f"Envio não encontrado: {id_}", codigo="envio_nao_encontrado")
        if em_uso is not None and em_uso(arq):
            raise Conflito("O arquivo está sendo usado por uma transcrição na fila ou em andamento.",
                           codigo="envio_em_uso", dica="Aguarde o fim da transcrição ou cancele-a.")
        arq.unlink()
        try:
            arq.parent.rmdir()  # só se ficou vazia (sem pasta de resultados)
        except OSError:
            pass
