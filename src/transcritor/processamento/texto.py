"""Normalização de texto para comparações internas (nunca altera o texto exibido)."""

from __future__ import annotations

import re
import unicodedata

_PONTUACAO = re.compile(r"[^\w\s%$]", flags=re.UNICODE)
_ESPACOS = re.compile(r"\s+")
FIM_DE_FRASE = (".", "?", "!", "…")


def normalizar(texto: str, remover_acentos: bool = False) -> str:
    """Minúsculas, sem pontuação e com espaços simples. Usado só para comparar hipóteses."""
    t = texto.lower().replace("’", "'")
    t = _PONTUACAO.sub(" ", t)
    if remover_acentos:
        t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    return _ESPACOS.sub(" ", t).strip()


def tokens(texto: str, remover_acentos: bool = False) -> list[str]:
    n = normalizar(texto, remover_acentos)
    return n.split() if n else []


def termina_frase(texto_palavra: str, reticencias: bool = True) -> bool:
    """A palavra encerra uma frase? Com reticencias=False, '...' e '…' (hesitação) não encerram."""
    t = texto_palavra.strip().rstrip("\"'”)]}")
    if not reticencias and (t.endswith("...") or t.endswith("…")):
        return False
    return t.endswith(FIM_DE_FRASE)


def juntar_palavras(textos: list[str]) -> str:
    """Concatena palavras no formato do Whisper (cada uma já traz o espaço inicial)."""
    bruto = "".join(textos)
    bruto = _ESPACOS.sub(" ", bruto).strip()
    return padronizar_tracos(bruto)


def padronizar_tracos(texto: str) -> str:
    """Travessões usados como pontuação viram vírgula; entre números viram hífen (intervalo)."""
    t = re.sub(r"(?<=\d)\s*[—–]\s*(?=\d)", "-", texto)
    t = re.sub(r"\s*[—–]+\s*", ", ", t)
    t = re.sub(r"^,\s*", "", t)
    t = re.sub(r",\s*([,.?!…])", r"\1", t)
    return t.strip()


def capitalizar_inicio(texto: str) -> str:
    """Maiúscula na primeira letra (ajuste tipográfico ao iniciar um novo turno de fala)."""
    for i, c in enumerate(texto):
        if c.isalpha():
            return texto[:i] + c.upper() + texto[i + 1 :]
        if c.isdigit():
            return texto
    return texto
