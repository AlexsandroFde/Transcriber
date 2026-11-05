"""Preparação do ambiente de execução.

* Console em UTF-8 (acentos no terminal do Windows).
* Telemetria das bibliotecas desligada: nenhum dado da reunião sai da máquina.
* Ordem de carga das DLLs CUDA (torch antes do CTranslate2 compartilha cuBLAS/cuDNN).
* Localização do ffmpeg e do token do Hugging Face.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import warnings
from pathlib import Path

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
    base = os.environ.get("APPDATA") if sys.platform == "win32" else os.environ.get("XDG_CONFIG_HOME")
    pasta = Path(base) if base else Path.home() / ".config"
    return pasta / "transcritor"


def pasta_modelos() -> Path:
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    else:
        base = Path.home() / ".cache"
    return base / "transcritor" / "modelos"


def arquivo_token() -> Path:
    return pasta_config() / "hf_token.txt"


def token_hf(explicito: str | None = None) -> str | None:
    """Token do Hugging Face: argumento, variável de ambiente, arquivo do transcritor ou login do hf."""
    if explicito:
        return explicito.strip()
    for var in ("TRANSCRITOR_HF_TOKEN", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        if os.environ.get(var):
            return os.environ[var].strip()
    arq = arquivo_token()
    if arq.exists():
        conteudo = arq.read_text(encoding="utf-8").strip()
        if conteudo:
            return conteudo
    try:
        from huggingface_hub import get_token

        return get_token()
    except Exception:
        return None


def salvar_token(token: str) -> Path:
    arq = arquivo_token()
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(token.strip() + "\n", encoding="utf-8")
    return arq


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
