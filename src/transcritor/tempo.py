"""Formatação de marcas de tempo."""

from __future__ import annotations


def _decompor(segundos: float) -> tuple[int, int, int, int]:
    total_ms = int(round(max(0.0, segundos) * 1000))
    h, resto = divmod(total_ms, 3_600_000)
    m, resto = divmod(resto, 60_000)
    s, ms = divmod(resto, 1000)
    return h, m, s, ms


def hms(segundos: float) -> str:
    """00:02:15 (segundos truncados, como em uma gravação)."""
    total = int(max(0.0, segundos))
    h, resto = divmod(total, 3600)
    m, s = divmod(resto, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def srt(segundos: float) -> str:
    h, m, s, ms = _decompor(segundos)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def vtt(segundos: float) -> str:
    h, m, s, ms = _decompor(segundos)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def duracao_legivel(segundos: float) -> str:
    """'1 h 05 min 12 s', '3 min 04 s' ou '12 s'."""
    total = int(round(max(0.0, segundos)))
    h, resto = divmod(total, 3600)
    m, s = divmod(resto, 60)
    if h:
        return f"{h} h {m:02d} min {s:02d} s"
    if m:
        return f"{m} min {s:02d} s"
    return f"{s} s"
