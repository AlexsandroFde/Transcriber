"""Operações do sistema: abrir arquivos e pastas com o programa padrão e informações gerais."""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
from pathlib import Path

from .. import __version__
from ..config import PREFIXO_API, Configuracoes
from ..erros import EntradaInvalida, NaoEncontrado
from .catalogo import EXTENSOES_MIDIA
from .contratos import InfoSistema, PastasSistema

log = logging.getLogger("transcritor.sistema")

# Por segurança, só arquivos gerados pelo programa, mídias e pastas podem ser abertos pela API
# (abrir um executável equivaleria a executá-lo).
EXTENSOES_ABRIR = {".docx", ".md", ".txt", ".srt", ".vtt", ".json", ".log", *EXTENSOES_MIDIA}


def abrir(caminho: str, revelar: bool = False) -> Path:
    alvo = Path(caminho).expanduser()
    if not alvo.exists():
        raise NaoEncontrado(f"Não encontrado: {alvo}", codigo="caminho_nao_encontrado",
                            dica="O arquivo ou a pasta pode ter sido movido ou apagado.")
    if alvo.is_file() and not revelar and alvo.suffix.lower() not in EXTENSOES_ABRIR:
        raise EntradaInvalida(f"Por segurança, arquivos {alvo.suffix or 'sem extensão'} não são abertos pelo "
                              "Transcritor.", codigo="tipo_nao_permitido",
                              dica="Use revelar=true para mostrar o arquivo na pasta.")
    alvo = alvo.resolve()
    if sys.platform == "win32":
        if revelar and alvo.is_file():
            subprocess.Popen(["explorer", f"/select,{alvo}"])
        else:
            os.startfile(str(alvo))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(alvo)] if revelar else ["open", str(alvo)])
    else:
        subprocess.Popen(["xdg-open", str(alvo.parent if revelar and alvo.is_file() else alvo)])
    log.info("Aberto%s: %s", " (revelar)" if revelar else "", alvo)
    return alvo


def informacoes(config: Configuracoes, modo: str) -> InfoSistema:
    return InfoSistema(
        versao=__version__, python=sys.version.split()[0], plataforma=platform.platform(), modo=modo,
        documentacao="/docs", openapi=f"{PREFIXO_API}/openapi.json",
        pastas=PastasSistema(config=str(config.pasta_config), dados=str(config.pasta_dados),
                             modelos=str(config.pasta_modelos), logs=str(config.pasta_logs),
                             envios=str(config.pasta_envios)),
        glossario_padrao=str(config.arquivo_glossario))
