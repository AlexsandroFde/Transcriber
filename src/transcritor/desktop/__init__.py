"""Inicializador do aplicativo (atalho "Transcritor").

Abre a janela, sobe o serviço local, garante uma única instância e encerra tudo ao fechar.
Uso: `transcritor-app [arquivos...] [--preparar]` (o atalho na Área de Trabalho chama este
programa; um vídeo arrastado sobre o atalho chega como argumento).

--preparar  baixa os modelos de IA logo ao abrir (usado pelo instalar.bat na primeira vez).
"""

from __future__ import annotations

import logging
import os
import sys


def _saidas_para_arquivo(pasta_logs) -> None:
    """Sem console (pythonw), mensagens soltas de bibliotecas vão para um arquivo em vez de se perderem."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    pasta_logs.mkdir(parents=True, exist_ok=True)
    arquivo = open(pasta_logs / "saida.log", "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = arquivo
    if sys.stderr is None:
        sys.stderr = arquivo


def _mensagem_nativa(titulo: str, texto: str) -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, texto, titulo, 0x40)  # MB_ICONINFORMATION


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    from .. import config
    from ..ambiente import configurar_log_aplicativo, preparar
    from .instancia import Instancia, arquivos_dos_argumentos

    preparar()
    cfg = config.obter()
    cfg.garantir_pastas()
    _saidas_para_arquivo(cfg.pasta_logs)
    configurar_log_aplicativo(cfg, console=sys.stderr is not None and getattr(sys.stderr, "isatty", lambda: False)())
    log = logging.getLogger("transcritor.desktop")
    arquivos = arquivos_dos_argumentos(argv)

    instancia = Instancia(cfg)
    if not instancia.adquirir():
        log.info("O Transcritor já está aberto; entregando %d arquivo(s) à instância existente.", len(arquivos))
        if not instancia.entregar(arquivos):
            _mensagem_nativa("Transcritor", "O Transcritor já está aberto, mas não respondeu.\n\n"
                                            "Aguarde alguns segundos e tente de novo. Se continuar, feche-o pelo Gerenciador "
                                            "de Tarefas.")
            return 1
        return 0

    log.info("Iniciando o aplicativo (pid %d)", os.getpid())
    from .janela import Aplicativo, modo_navegador

    codigo = 0
    app = Aplicativo(cfg, instancia, arquivos, preparar="--preparar" in argv)
    try:
        try:
            app.executar()
        except Exception:
            if app.janela is not None and app.servidor is not None:
                raise
            log.exception("A janela do aplicativo não pôde ser aberta; usando o navegador padrão.")
            app.encerrar()
            modo_navegador(cfg, instancia, arquivos)
    except Exception:
        log.exception("Falha no aplicativo")
        codigo = 1
    finally:
        app.encerrar()
        instancia.liberar()
        log.info("Aplicativo encerrado")
        logging.shutdown()
    # Encerra sem esperar threads de bibliotecas da janela: o serviço e as tarefas já foram finalizados.
    os._exit(codigo)
