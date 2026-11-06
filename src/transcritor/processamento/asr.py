"""Reconhecimento de fala com faster-whisper (Whisper large-v3 por padrão).

Estratégia do primeiro passo:
  * Só os trechos com fala (VAD Silero unido à diarização) são enviados ao modelo; silêncios
    longos são removidos, pois é neles que o Whisper "inventa" frases. Pausas curtas (< ~2 s)
    são mantidas para não cortar palavras nem quebrar a naturalidade da fala.
  * A transcrição é contínua, com o texto anterior condicionando o seguinte (contexto entre
    janelas de 30 s), idioma fixo em português e busca em feixe.
  * O prompt inicial contém o contexto da reunião e um trecho coloquial com hesitações, que
    orienta o modelo a transcrever de forma literal ("tá", "né", repetições) em vez de "limpar".
  * O glossário entra como hotwords, que acompanham todas as janelas da gravação.
"""

from __future__ import annotations

import bisect
import logging
import os
from typing import Callable

import numpy as np

from ..ambiente import carregar_torch, cuda_disponivel
from .audio import TAXA
from .intervalos import Intervalo, expandir, unir
from .modelos import Palavra, SegmentoASR

log = logging.getLogger("transcritor")

# Trecho coloquial: incentiva transcrição literal (hesitações, repetições, formas como "tá", "tava").
PRIMER_LITERAL = "Hum, deixa eu ver... Tá, então, é, a gente, a gente tava pensando, né, em fazer assim."

LIMITE_PROMPT_TOKENS = 200
LIMITE_HOTWORDS_TOKENS = 60


class MapaFala:
    """Concatena trechos de fala e converte tempos do áudio concatenado para o original."""

    def __init__(self, trechos: list[Intervalo]):
        self.amostras = [(int(round(a * TAXA)), int(round(b * TAXA))) for a, b in trechos]
        self.offsets: list[int] = []
        acumulado = 0
        for a, b in self.amostras:
            self.offsets.append(acumulado)
            acumulado += b - a
        self.total = acumulado

    @property
    def duracao(self) -> float:
        return self.total / TAXA

    def concatenar(self, audio: np.ndarray) -> np.ndarray:
        if not self.amostras:
            return np.zeros(0, dtype=np.float32)
        return np.ascontiguousarray(np.concatenate([audio[a:b] for a, b in self.amostras]), dtype=np.float32)

    def _indice(self, t: float) -> int:
        i = bisect.bisect_right(self.offsets, t * TAXA) - 1
        return max(0, min(i, len(self.offsets) - 1))

    def para_original(self, t: float, indice: int | None = None) -> float:
        i = self._indice(t) if indice is None else indice
        a, b = self.amostras[i]
        s = min(max(t * TAXA - self.offsets[i], 0.0), float(b - a))
        return (a + s) / TAXA

    def mapear(self, ini: float, fim: float) -> tuple[float, float]:
        """Mapeia um intervalo; se ele atravessar uma junção, fica do lado com mais conteúdo."""
        i = self._indice(ini)
        j = self._indice(max(ini, fim - 1e-3))
        if i == j:
            return self.para_original(ini, i), self.para_original(fim, i)
        fim_i = (self.offsets[i] + self.amostras[i][1] - self.amostras[i][0]) / TAXA
        if fim_i - ini >= fim - fim_i:
            return self.para_original(ini, i), self.para_original(fim_i, i)
        ini_j = self.offsets[j] / TAXA
        return self.para_original(ini_j, j), self.para_original(fim, j)


def construir_trechos(regioes: list[Intervalo], duracao: float, margem: float = 0.3,
                      juntar: float = 1.5) -> list[Intervalo]:
    """Expande as regiões de fala e une as próximas (mantém pausas naturais)."""
    return unir(expandir(regioes, margem, duracao), tolerancia=juntar)


class Reconhecedor:
    def __init__(self, nome_modelo: str = "large-v3", dispositivo: str = "auto", precisao: str = "auto"):
        carregar_torch()  # garante as DLLs CUDA antes do CTranslate2
        from faster_whisper import WhisperModel
        from faster_whisper.tokenizer import Tokenizer

        if dispositivo == "auto":
            dispositivo = "cuda" if cuda_disponivel() else "cpu"
        if precisao == "auto":
            precisao = "float16" if dispositivo == "cuda" else "int8"
        self.nome = nome_modelo
        self.dispositivo = dispositivo
        self.precisao = precisao
        threads = max(1, (os.cpu_count() or 4) // 2)
        self.modelo = WhisperModel(nome_modelo, device=dispositivo, compute_type=precisao,
                                   cpu_threads=threads if dispositivo == "cpu" else 0)
        self.tokenizer = Tokenizer(self.modelo.hf_tokenizer, multilingual=True, task="transcribe", language="pt")

    def contar_tokens(self, texto: str) -> int:
        return len(self.tokenizer.encode(" " + texto.strip())) if texto.strip() else 0

    def truncar_final(self, texto: str, limite: int) -> str:
        """Mantém o final do texto dentro do limite de tokens (o mais recente é o mais útil)."""
        palavras = texto.split()
        while palavras and self.contar_tokens(" ".join(palavras)) > limite:
            palavras = palavras[max(1, len(palavras) // 10):]
        return " ".join(palavras)

    def transcrever(
        self,
        audio: np.ndarray,
        prompt: str | None = None,
        hotwords: str | None = None,
        condicionar: bool = True,
        beam: int = 5,
        paciencia: float = 1.0,
        temperaturas: tuple[float, ...] = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
        progresso: Callable[[float], None] | None = None,
    ) -> list[SegmentoASR]:
        """Transcreve um array de áudio 16 kHz. Tempos relativos ao início do array."""
        duracao = len(audio) / TAXA
        if duracao <= 0.05:
            return []
        segmentos, _info = self.modelo.transcribe(
            audio,
            language="pt",
            task="transcribe",
            beam_size=beam,
            best_of=5,
            patience=paciencia,
            temperature=list(temperaturas),
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
            condition_on_previous_text=condicionar,
            prompt_reset_on_temperature=0.5,
            initial_prompt=prompt or None,
            hotwords=hotwords or None,
            word_timestamps=True,
            without_timestamps=False,
            vad_filter=False,
            suppress_blank=True,
            suppress_tokens=[-1],
            max_initial_timestamp=1.0,
        )
        saida: list[SegmentoASR] = []
        for s in segmentos:
            palavras = [
                Palavra(float(w.start), float(w.end), w.word, float(w.probability))
                for w in (s.words or [])
                if w.word.strip()
            ]
            saida.append(
                SegmentoASR(float(s.start), float(s.end), s.text, float(s.avg_logprob),
                            float(s.compression_ratio), float(s.no_speech_prob),
                            float(s.temperature or 0.0), palavras)
            )
            if progresso:
                progresso(min(1.0, float(s.end) / duracao))
        return saida

    def liberar(self) -> None:
        try:
            del self.modelo
        except AttributeError:
            pass
        import gc

        gc.collect()


def montar_prompt(rec: Reconhecedor, contexto: str | None, literal: bool = True) -> str:
    partes = []
    if contexto and contexto.strip():
        c = contexto.strip()
        partes.append(c if c.endswith((".", "?", "!")) else c + ".")
    if literal:
        partes.append(PRIMER_LITERAL)
    prompt = " ".join(partes)
    if rec.contar_tokens(prompt) > LIMITE_PROMPT_TOKENS:
        # O primer fica no fim (mais próximo do áudio); o contexto é truncado pelo início.
        prompt = rec.truncar_final(prompt, LIMITE_PROMPT_TOKENS)
    return prompt


def montar_hotwords(rec: Reconhecedor, termos: list[str], limite: int = LIMITE_HOTWORDS_TOKENS) -> str:
    escolhidos: list[str] = []
    vistos: set[str] = set()
    for t in termos:
        t = t.strip()
        if not t or t.lower() in vistos:
            continue
        candidato = ", ".join(escolhidos + [t])
        if rec.contar_tokens(candidato) > limite:
            break
        escolhidos.append(t)
        vistos.add(t.lower())
    return ", ".join(escolhidos)


def passo1(
    rec: Reconhecedor,
    audio: np.ndarray,
    regioes_fala: list[Intervalo],
    prompt: str,
    hotwords: str,
    beam: int = 5,
    progresso: Callable[[float], None] | None = None,
) -> tuple[list[SegmentoASR], list[Intervalo]]:
    """Transcrição contínua de todos os trechos de fala, com tempos no relógio original."""
    duracao = len(audio) / TAXA
    trechos = construir_trechos(regioes_fala, duracao)
    if not trechos:
        return [], []
    mapa = MapaFala(trechos)
    concatenado = mapa.concatenar(audio)
    log.debug("Passo 1: %.1f s de áudio com fala (de %.1f s)", mapa.duracao, duracao)
    segmentos = rec.transcrever(concatenado, prompt=prompt, hotwords=hotwords, condicionar=True,
                                beam=beam, progresso=progresso)
    del concatenado
    for s in segmentos:
        s.inicio, s.fim = mapa.para_original(s.inicio), mapa.para_original(max(s.inicio, s.fim - 1e-3))
        for p in s.palavras:
            p.inicio, p.fim = mapa.mapear(p.inicio, p.fim)
        if s.palavras:
            s.inicio = min(s.inicio, s.palavras[0].inicio)
            s.fim = max(s.fim, s.palavras[-1].fim)
    return segmentos, trechos
