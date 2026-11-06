"""Preparação do ambiente de execução.

* Console em UTF-8 (acentos no terminal do Windows).
* Telemetria das bibliotecas desligada: nenhum dado da reunião sai da máquina.
* Ordem de carga das DLLs CUDA (torch antes do CTranslate2 compartilha cuBLAS/cuDNN).
* Localização do ffmpeg e do token do Hugging Face.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import shutil
import sys
import warnings
from pathlib import Path

from . import config

log = logging.getLogger("transcritor")

_PREPARADO = False


def preparar() -> None:
    """Deve ser chamado antes de importar torch, pyannote ou faster_whisper."""
    global _PREPARADO
    if _PREPARADO:
        return
    _PREPARADO = True

    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass

    # Privacidade: desliga telemetria (pyannote envia métricas de uso por padrão).
    os.environ["PYANNOTE_METRICS_ENABLED"] = "false"
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("DO_NOT_TRACK", "1")
    # Ruído de console e compatibilidade no Windows.
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    # torch e CTranslate2 trazem cada um sua cópia do OpenMP (libiomp5md.dll).
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

    for nome in ("torch.utils.flop_counter", "torch._subclasses", "lightning", "pytorch_lightning",
                 "lightning_fabric", "speechbrain", "pyannote", "faster_whisper"):
        logging.getLogger(nome).setLevel(logging.ERROR)
    warnings.filterwarnings("ignore", message=r".*torchcodec is not installed correctly.*")
    warnings.filterwarnings("ignore", message=r".*TensorFloat-32.*")
    warnings.filterwarnings("ignore", message=r".*std\(\): degrees of freedom.*")
    warnings.filterwarnings("ignore", category=FutureWarning)


def carregar_torch():
    """Importa o torch primeiro para que suas DLLs CUDA fiquem disponíveis ao CTranslate2."""
    preparar()
    import torch

    if sys.platform == "win32":
        lib = Path(torch.__file__).parent / "lib"
        if lib.is_dir():
            try:
                os.add_dll_directory(str(lib))
            except OSError:
                pass
    return torch


def cuda_disponivel() -> bool:
    try:
        torch = carregar_torch()
        if not torch.cuda.is_available():
            return False
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception as e:  # pragma: no cover - depende do hardware
        log.debug("CUDA indisponível: %s", e)
        return False


def descrever_gpu() -> str:
    try:
        torch = carregar_torch()
        if torch.cuda.is_available():
            p = torch.cuda.get_device_properties(0)
            return f"{p.name} ({p.total_memory / 2**30:.1f} GB)"
    except Exception:
        pass
    return "nenhuma (CPU)"


def caminho_ffmpeg() -> str:
    """ffmpeg definido pelo usuário, do sistema ou o embutido no pacote imageio-ffmpeg."""
    definido = os.environ.get("TRANSCRITOR_FFMPEG")
    if definido and Path(definido).exists():
        return definido
    sistema = shutil.which("ffmpeg")
    if sistema:
        return sistema
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def pasta_config() -> Path:
    return config.obter().pasta_config


def pasta_modelos() -> Path:
    return config.obter().pasta_modelos


def arquivo_token() -> Path:
    return config.obter().arquivo_token


VARIAVEIS_TOKEN = ("TRANSCRITOR_HF_TOKEN", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")


def localizar_token(explicito: str | None = None) -> tuple[str | None, str | None]:
    """(token, origem). Ordem: argumento, variável de ambiente, arquivo do transcritor, login do hf.

    origem: "parametro", "variavel_ambiente:<NOME>", "arquivo", "login_huggingface" ou None.
    """
    if explicito and explicito.strip():
        return explicito.strip(), "parametro"
    for var in VARIAVEIS_TOKEN:
        if os.environ.get(var, "").strip():
            return os.environ[var].strip(), f"variavel_ambiente:{var}"
    arq = arquivo_token()
    if arq.exists():
        conteudo = arq.read_text(encoding="utf-8").strip()
        if conteudo:
            return conteudo, "arquivo"
    try:
        from huggingface_hub import get_token

        token = get_token()
        return (token, "login_huggingface") if token else (None, None)
    except Exception:
        return None, None


def token_hf(explicito: str | None = None) -> str | None:
    """Token do Hugging Face: argumento, variável de ambiente, arquivo do transcritor ou login do hf."""
    return localizar_token(explicito)[0]


def salvar_token(token: str) -> Path:
    arq = arquivo_token()
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(token.strip() + "\n", encoding="utf-8")
    return arq


def remover_token() -> bool:
    """Apaga o token salvo pelo transcritor. Retorna False se não havia arquivo."""
    arq = arquivo_token()
    if not arq.exists():
        return False
    arq.unlink()
    return True


def configurar_log(arquivo: Path | None = None, detalhado: bool = False) -> None:
    """Console (um único handler) e, opcionalmente, arquivo de log (substitui o anterior)."""
    raiz = logging.getLogger("transcritor")
    raiz.setLevel(logging.DEBUG)
    raiz.propagate = False
    console = next((h for h in raiz.handlers if getattr(h, "_transcritor_console", False)), None)
    if console is None:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter("%(message)s"))
        console._transcritor_console = True  # type: ignore[attr-defined]
        raiz.addHandler(console)
    console.setLevel(logging.DEBUG if detalhado else logging.INFO)
    for h in list(raiz.handlers):
        if getattr(h, "_transcritor_arquivo", False):
            raiz.removeHandler(h)
            h.close()
    if arquivo is not None:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(arquivo, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        fh._transcritor_arquivo = True  # type: ignore[attr-defined]
        raiz.addHandler(fh)


FORMATO_LOG_APLICATIVO = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"


def configurar_log_aplicativo(cfg: config.Configuracoes, console: bool = True) -> Path:
    """Registro do servidor e do inicializador: arquivo rotativo e, se houver, o console.

    Usa a raiz do `logging` (as mensagens do processamento, no logger "transcritor", só são
    configuradas nos processos trabalhadores, que têm registro próprio por tarefa).
    """
    cfg.pasta_logs.mkdir(parents=True, exist_ok=True)
    arquivo = cfg.pasta_logs / "transcritor.log"
    raiz = logging.getLogger()
    raiz.setLevel(getattr(logging, cfg.nivel_log, logging.INFO))
    for h in list(raiz.handlers):
        if getattr(h, "_transcritor_app", False):
            raiz.removeHandler(h)
            h.close()
    fh = logging.handlers.RotatingFileHandler(arquivo, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter(FORMATO_LOG_APLICATIVO))
    fh._transcritor_app = True  # type: ignore[attr-defined]
    raiz.addHandler(fh)
    if console and sys.stderr is not None:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"))
        sh._transcritor_app = True  # type: ignore[attr-defined]
        raiz.addHandler(sh)
    # Neste processo, o logger "transcritor" apenas repassa à raiz (sem console próprio).
    proc = logging.getLogger("transcritor")
    for h in list(proc.handlers):
        if getattr(h, "_transcritor_console", False) or getattr(h, "_transcritor_arquivo", False):
            proc.removeHandler(h)
    proc.setLevel(logging.NOTSET)
    proc.propagate = True
    for nome in ("uvicorn", "uvicorn.error"):
        logging.getLogger(nome).setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    return arquivo
