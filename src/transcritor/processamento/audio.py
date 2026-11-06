"""Extração do áudio do vídeo e pré-processamento adaptativo.

Fluxo:
  1. ffmpeg extrai a faixa de áudio para WAV float 16 kHz (sem compressão com perdas).
  2. Os canais são analisados: canal mudo ou com fase invertida não entra na mixagem.
  3. Filtro passa-altas suave (remove ronco e zumbido de rede elétrica).
  4. VAD (Silero) localiza a fala para medir nível de voz, ruído de fundo e variação de volume.
  5. Normalização de volume da fala; redução de ruído e normalização dinâmica só quando
     as medições indicam necessidade (modo "auto"), pois filtros agressivos criam artefatos
     que pioram o reconhecimento.

São gerados dois arquivos: `audio_base.wav` (sem redução de ruído, usado na diarização,
pois preserva o timbre de cada voz) e `audio_asr.wav` (usado no reconhecimento de fala).
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .intervalos import Intervalo

log = logging.getLogger("transcritor")

TAXA = 16000
NIVEL_ALVO_DB = -20.0  # nível RMS desejado para a fala, em dBFS


@dataclass
class InfoMidia:
    caminho: str
    duracao: float | None
    tem_video: bool
    faixas_audio: list[dict] = field(default_factory=list)


def sondar(caminho: Path) -> InfoMidia:
    """Lê duração e faixas de áudio do arquivo de mídia."""
    import av

    with av.open(str(caminho)) as c:
        duracao = float(c.duration / av.time_base) if c.duration else None
        faixas = []
        for k, s in enumerate(c.streams.audio):
            cc = s.codec_context
            faixas.append(
                {
                    "indice_audio": k,
                    "canais": int(getattr(cc, "channels", 0) or 0),
                    "taxa": int(cc.sample_rate or 0),
                    "codec": cc.name,
                    "idioma": s.language or (s.metadata or {}).get("language"),
                    "titulo": (s.metadata or {}).get("title"),
                }
            )
        tem_video = len(c.streams.video) > 0
    return InfoMidia(str(caminho), duracao, tem_video, faixas)


_SOXR: bool | None = None


def _tem_soxr(ffmpeg: str) -> bool:
    global _SOXR
    if _SOXR is None:
        cmd = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i",
               "anullsrc=r=44100:cl=mono", "-t", "0.1", "-af", "aresample=16000:resampler=soxr",
               "-f", "null", "-"]
        try:
            _SOXR = subprocess.run(cmd, capture_output=True, timeout=60).returncode == 0
        except Exception:
            _SOXR = False
    return _SOXR


def _executar_ffmpeg(cmd: list[str], duracao: float | None, progresso: Callable[[float], None] | None) -> None:
    """Executa o ffmpeg lendo o progresso (-progress pipe:1) e coletando erros."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace")
    erros: list[str] = []

    def drenar():
        assert proc.stderr is not None
        for linha in proc.stderr:
            erros.append(linha.rstrip())

    t = threading.Thread(target=drenar, daemon=True)
    t.start()
    assert proc.stdout is not None
    for linha in proc.stdout:
        if progresso and duracao and linha.startswith("out_time_us="):
            try:
                us = int(linha.split("=", 1)[1])
                progresso(min(1.0, us / 1e6 / duracao))
            except ValueError:
                pass
    proc.wait()
    t.join(timeout=5)
    if proc.returncode != 0:
        raise RuntimeError("Falha no ffmpeg:\n" + "\n".join(erros[-20:]))


def extrair_audio(
    ffmpeg: str,
    entrada: Path,
    saida: Path,
    info: InfoMidia,
    faixa: str = "0",
    progresso: Callable[[float], None] | None = None,
) -> dict:
    """Extrai a faixa escolhida para WAV float 16 kHz preservando até 2 canais para análise."""
    if not info.faixas_audio:
        raise RuntimeError(f"O arquivo não possui faixa de áudio: {entrada}")
    resample = "aresample=16000:resampler=soxr" if _tem_soxr(ffmpeg) else "aresample=16000"
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-progress", "pipe:1",
           "-i", str(entrada)]
    if faixa == "todas" and len(info.faixas_audio) > 1:
        n = len(info.faixas_audio)
        entradas = "".join(f"[0:a:{k}]" for k in range(n))
        cmd += ["-filter_complex", f"{entradas}amix=inputs={n}:normalize=0,{resample}[a]", "-map", "[a]"]
        canais = max(min(f["canais"] or 1, 2) for f in info.faixas_audio)
        descricao = f"mixagem das {n} faixas de áudio"
    else:
        k = 0 if faixa == "todas" else int(faixa)
        if k >= len(info.faixas_audio):
            raise RuntimeError(f"Faixa de áudio {k} não existe (o arquivo tem {len(info.faixas_audio)}).")
        cmd += ["-map", f"0:a:{k}", "-af", resample]
        canais = min(info.faixas_audio[k]["canais"] or 1, 2)
        descricao = f"faixa de áudio {k}"
    cmd += ["-vn", "-sn", "-dn", "-ac", str(max(1, canais)), "-ar", str(TAXA), "-c:a", "pcm_f32le", str(saida)]
    _executar_ffmpeg(cmd, info.duracao, progresso)
    return {"faixa": descricao, "canais_extraidos": canais, "reamostragem": resample}


# ---------------------------------------------------------------------------
# Análise e tratamento
# ---------------------------------------------------------------------------


def _db(x: float) -> float:
    return float(20.0 * np.log10(max(x, 1e-10)))


def tratar_canais(dados: np.ndarray) -> tuple[np.ndarray, dict]:
    """Converte para mono evitando cancelamento de fase e canais mudos."""
    if dados.ndim == 1 or dados.shape[1] == 1:
        return np.ascontiguousarray(dados.reshape(-1), dtype=np.float32), {"decisao": "áudio mono"}
    esq = dados[:, 0]
    dir_ = dados[:, 1]
    bloco = TAXA * 30
    s_ll = s_rr = s_lr = 0.0
    for i in range(0, len(esq), bloco):
        a = esq[i : i + bloco].astype(np.float64)
        b = dir_[i : i + bloco].astype(np.float64)
        s_ll += float(a @ a)
        s_rr += float(b @ b)
        s_lr += float(a @ b)
    n = max(1, len(esq))
    nivel_e, nivel_d = _db(np.sqrt(s_ll / n)), _db(np.sqrt(s_rr / n))
    corr = s_lr / max(np.sqrt(s_ll * s_rr), 1e-20)
    info = {"nivel_esquerdo_db": round(nivel_e, 1), "nivel_direito_db": round(nivel_d, 1),
            "correlacao": round(float(corr), 3)}
    if nivel_e - nivel_d > 25:
        info["decisao"] = "canal direito praticamente mudo: usado só o esquerdo"
        mono = esq
    elif nivel_d - nivel_e > 25:
        info["decisao"] = "canal esquerdo praticamente mudo: usado só o direito"
        mono = dir_
    elif corr < -0.3:
        info["decisao"] = "canais com fase invertida: usado só o mais forte (a soma cancelaria a voz)"
        mono = esq if nivel_e >= nivel_d else dir_
    else:
        info["decisao"] = "mixagem dos dois canais"
        mono = (esq + dir_) * 0.5
    return np.ascontiguousarray(mono, dtype=np.float32), info


def passa_altas(x: np.ndarray, corte_hz: float = 70.0) -> np.ndarray:
    from scipy.signal import butter, sosfilt

    sos = butter(2, corte_hz, btype="highpass", fs=TAXA, output="sos")
    return sosfilt(sos, x).astype(np.float32)


def normalizar_pico(x: np.ndarray, alvo_db: float = -1.0) -> np.ndarray:
    """Ganho para que o percentil 99,99 do valor absoluto fique em `alvo_db`."""
    if len(x) == 0:
        return x
    amostra = np.abs(x[:: max(1, len(x) // 2_000_000)])
    pico = float(np.percentile(amostra, 99.99)) if len(amostra) else 0.0
    if pico <= 1e-6:
        return x
    ganho = (10 ** (alvo_db / 20.0)) / pico
    return (x * ganho).astype(np.float32)


def detectar_fala(x: np.ndarray, limiar: float = 0.4) -> list[Intervalo]:
    """Regiões de fala (Silero VAD) com granularidade fina."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    opcoes = VadOptions(threshold=limiar, min_speech_duration_ms=150, min_silence_duration_ms=300,
                        speech_pad_ms=100)
    trechos = get_speech_timestamps(x, opcoes, sampling_rate=TAXA)
    return [(t["start"] / TAXA, t["end"] / TAXA) for t in trechos]


def _niveis_quadro(x: np.ndarray, quadro_s: float = 0.03) -> np.ndarray:
    q = int(TAXA * quadro_s)
    n = len(x) // q
    if n == 0:
        return np.array([-100.0])
    m = x[: n * q].reshape(n, q).astype(np.float64)
    rms = np.sqrt(np.mean(m * m, axis=1))
    return 20.0 * np.log10(np.maximum(rms, 1e-10))


def medir(x: np.ndarray, fala: list[Intervalo]) -> dict:
    """Nível da fala, ruído de fundo, SNR estimada e dispersão de volume entre trechos."""
    quadro_s = 0.03
    niveis = _niveis_quadro(x, quadro_s)
    mascara = np.zeros(len(niveis), dtype=bool)
    for a, b in fala:
        mascara[int(a / quadro_s) : int(np.ceil(b / quadro_s))] = True
    validos = niveis > -90
    fala_n = niveis[mascara & validos]
    ruido_n = niveis[~mascara & validos]
    nivel_fala = float(np.percentile(fala_n, 50)) if len(fala_n) else float(np.percentile(niveis, 90))
    pico_fala = float(np.percentile(fala_n, 95)) if len(fala_n) else nivel_fala
    if len(ruido_n) >= 30:
        nivel_ruido = float(np.percentile(ruido_n, 50))
    else:
        nivel_ruido = float(np.percentile(niveis[validos], 5)) if validos.any() else -90.0
    niveis_trechos = []
    for a, b in fala:
        if b - a >= 0.5:
            seg = niveis[int(a / quadro_s) : int(b / quadro_s)]
            seg = seg[seg > -90]
            if len(seg):
                niveis_trechos.append(float(np.percentile(seg, 75)))
    dispersao = float(np.percentile(niveis_trechos, 90) - np.percentile(niveis_trechos, 10)) if len(niveis_trechos) >= 5 else 0.0
    return {
        "nivel_fala_db": round(nivel_fala, 1),
        "pico_fala_db": round(pico_fala, 1),
        "nivel_ruido_db": round(nivel_ruido, 1),
        "snr_db": round(pico_fala - nivel_ruido, 1),
        "dispersao_volume_db": round(dispersao, 1),
        "fala_detectada_s": round(sum(b - a for a, b in fala), 1),
    }


def aplicar_ganho_fala(x: np.ndarray, nivel_fala_db: float) -> tuple[np.ndarray, float]:
    ganho_db = float(np.clip(NIVEL_ALVO_DB - nivel_fala_db, -20.0, 40.0))
    return (x * (10 ** (ganho_db / 20.0))).astype(np.float32), ganho_db


@dataclass
class ResultadoPreprocessamento:
    modo: str
    canais: dict
    medicoes: dict
    filtros_asr: list[str]
    ganho_base_db: float
    ganho_asr_db: float | None
    observacoes: list[str]

    def para_dict(self) -> dict:
        return asdict(self)


def preprocessar(
    ffmpeg: str,
    extraido: Path,
    destino_base: Path,
    destino_asr: Path,
    modo: str = "auto",
) -> tuple[ResultadoPreprocessamento, list[Intervalo]]:
    """Gera audio_base.wav e audio_asr.wav. Retorna o relatório e as regiões de fala (VAD)."""
    import soundfile as sf

    dados, taxa = sf.read(str(extraido), dtype="float32", always_2d=True)
    if taxa != TAXA:
        raise RuntimeError(f"Taxa inesperada após extração: {taxa}")
    mono, info_canais = tratar_canais(dados)
    del dados
    observacoes: list[str] = []

    if modo == "nenhum":
        x = normalizar_pico(mono, -3.0)
    else:
        x = normalizar_pico(passa_altas(mono), -3.0)
    del mono

    fala = detectar_fala(x)
    med = medir(x, fala)
    if not fala:
        observacoes.append("Nenhuma fala detectada pelo VAD; o áudio pode estar mudo ou muito ruidoso.")

    if modo == "nenhum":
        ganho_base = 0.0
    else:
        x, ganho_base = aplicar_ganho_fala(x, med["nivel_fala_db"])
    sf.write(str(destino_base), x, TAXA, subtype="FLOAT")

    filtros: list[str] = []
    if modo in ("auto", "forte"):
        ruido_ref = float(np.clip(med["nivel_ruido_db"] + ganho_base, -80.0, -20.0))
        if modo == "forte" or med["snr_db"] < 15.0:
            nr = 18 if modo == "forte" else 10
            filtros.append(f"afftdn=nr={nr}:nf={ruido_ref:.0f}:tn=1")
            observacoes.append(f"Redução de ruído aplicada (SNR estimada {med['snr_db']} dB).")
        if modo == "forte" or med["dispersao_volume_db"] > 10.0:
            limiar = 10 ** ((ruido_ref + 6.0) / 20.0)
            filtros.append(f"dynaudnorm=f=400:g=21:p=0.9:m=8:t={limiar:.6f}")
            observacoes.append(
                f"Normalização dinâmica aplicada (variação de volume entre trechos de {med['dispersao_volume_db']} dB)."
            )

    ganho_asr = None
    if filtros:
        temp = destino_asr.with_suffix(".tmp.wav")
        cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-i", str(destino_base),
               "-af", ",".join(filtros), "-c:a", "pcm_f32le", "-ar", str(TAXA), "-ac", "1", str(temp)]
        _executar_ffmpeg(cmd, None, None)
        y, _ = sf.read(str(temp), dtype="float32")
        temp.unlink(missing_ok=True)
        med_y = medir(y, fala)
        y, ganho_asr = aplicar_ganho_fala(y, med_y["nivel_fala_db"])
        sf.write(str(destino_asr), y, TAXA, subtype="FLOAT")
    else:
        destino_asr.write_bytes(destino_base.read_bytes())

    res = ResultadoPreprocessamento(modo, info_canais, med, filtros, round(ganho_base, 1),
                                    None if ganho_asr is None else round(ganho_asr, 1), observacoes)
    return res, fala


def carregar_wav(caminho: Path) -> np.ndarray:
    import soundfile as sf

    x, taxa = sf.read(str(caminho), dtype="float32")
    if taxa != TAXA:
        raise RuntimeError(f"Taxa inesperada em {caminho}: {taxa}")
    return np.ascontiguousarray(x.reshape(-1))


def salvar_json(caminho: Path, dados: dict) -> None:
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
