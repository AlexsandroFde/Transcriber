"""Segundo passo: revisão dos trechos duvidosos e recuperação de fala omitida.

Alvos da revisão:
  * segmentos marcados pelo diagnóstico (laço de repetição, taxa de fala implausível,
    confiança média baixa, palavras com duração anômala);
  * palavras de baixa probabilidade, ou longas demais em tokens (típico de palavra inventada);
  * respostas curtas isoladas ("Certo.", "Exato."), que o modelo erra com frequência;
  * lacunas: regiões em que a diarização/VAD detectou fala mas não há nenhuma palavra
    (o Whisper às vezes "pula" trechos inteiros em gravações longas).

Para cada alvo, uma janela de áudio com limites em pausas (sem cortar palavras) é
decodificada mais duas vezes, em condições diferentes: (2) com o texto anterior da reunião
como contexto e feixe largo; (3) sem contexto e com uma janela acústica maior. As três
hipóteses são combinadas palavra a palavra por maioria (ver `qualidade.combinar`):
o que a maioria confirma fica; o que só uma decodificação "ouviu" é descartado; palavras do
primeiro passo nunca são apagadas sem aviso; sem maioria, o trecho é sinalizado como incerto.
Lacunas que continuam sem texto viram [inaudível].
"""

from __future__ import annotations

import bisect
import copy
import logging
from dataclasses import asdict, dataclass, field, replace
from typing import Callable

import numpy as np

from .asr import Reconhecedor
from .audio import TAXA
from .intervalos import Intervalo, filtrar_minimo, subtrair, unir
from .modelos import Marcador, Palavra, SegmentoASR
from .qualidade import (OpcoesVotacao, assinatura_alucinacao, combinar, eco_do_prompt, evidencia_fala,
                        pares_alinhados,
                        repeticao_excessiva)
from .texto import juntar_palavras, termina_frase, tokens

log = logging.getLogger("transcritor")


@dataclass
class OpcoesRevisao:
    limiar_palavra: float = 0.6  # palavras abaixo disso disparam revisão
    limiar_palavra_longa: float = 0.9  # palavra com muitos tokens (típico de palavra inventada)
    tokens_palavra_longa: int = 5
    limiar_frase_curta: float = 0.85  # respostas curtas isoladas ("Certo.", "Exato.")
    lacuna_minima: float = 0.5  # fala sem nenhuma palavra a partir disso (s) é revisada
    inaudivel_minimo: float = 1.2  # lacuna que continua sem texto vira [inaudível]
    beam: int = 10
    paciencia: float = 2.0
    margem_alternativa: float = 1.0  # a 3ª hipótese usa uma janela acústica maior
    limiar_sem_maioria: float = 0.85
    prob_minima_manter: float = 0.4
    prob_minima_insercao: float = 0.4
    limiar_absoluto: float = 0.15
    janela_minima: float = 3.0
    janela_maxima: float = 28.0
    contexto_janela: float = 1.0


@dataclass
class Janela:
    inicio: float
    fim: float
    motivos: set[str] = field(default_factory=set)


@dataclass
class RegistroRevisao:
    inicio: float
    fim: float
    motivos: list[str]
    alterado: bool
    texto_passo1: str
    texto_revisao: str
    texto_alternativo: str
    texto_final: str

    def para_dict(self) -> dict:
        d = asdict(self)
        d["inicio"] = round(self.inicio, 2)
        d["fim"] = round(self.fim, 2)
        return d


def cobertura_palavras(palavras: list[Palavra], folga: float = 0.15) -> list[Intervalo]:
    return unir(((p.inicio - folga, p.fim + folga) for p in palavras))


def lacunas(fala_ref: list[Intervalo], palavras: list[Palavra], minimo: float) -> list[Intervalo]:
    """Fala detectada que não está coberta por nenhuma palavra."""
    return filtrar_minimo(subtrair(fala_ref, cobertura_palavras(palavras)), minimo)


def _pausas(palavras: list[Palavra], duracao: float, minimo: float = 0.2) -> list[Intervalo]:
    pausas: list[Intervalo] = []
    anterior = 0.0
    for p in palavras:
        if p.inicio - anterior >= minimo:
            pausas.append((anterior, p.inicio))
        anterior = max(anterior, p.fim)
    if duracao - anterior >= minimo:
        pausas.append((anterior, duracao))
    return pausas


def _encaixar(t: float, palavras: list[Palavra], inicios: list[float], pausas: list[Intervalo],
              lado: int, alcance: float = 0.6) -> float:
    """Ajusta um limite de janela sem cortar palavras, movendo-o apenas para fora.

    lado -1: início da janela (só recua); lado +1: fim da janela (só avança).
    1. Se `t` cai dentro de uma palavra, vai para a borda externa dela.
    2. Se houver uma pausa logo além (até `alcance`), entra um pouco nela, para que o
       limite fique em silêncio e não colado na palavra.
    """
    for _ in range(len(palavras) + 1):
        k = bisect.bisect_right(inicios, t) - 1
        dentro = [palavras[i] for i in (k - 1, k) if 0 <= i < len(palavras) and palavras[i].inicio < t < palavras[i].fim]
        if not dentro:
            break
        t = min(p.inicio for p in dentro) - 0.05 if lado < 0 else max(p.fim for p in dentro) + 0.05
    for a, b in (reversed(pausas) if lado < 0 else pausas):
        if lado < 0 and t - alcance <= b <= t + 1e-6:
            return min(t, b - min(0.15, (b - a) / 2))
        if lado > 0 and t - 1e-6 <= a <= t + alcance:
            return max(t, a + min(0.15, (b - a) / 2))
    return t


def montar_janelas(alvos: list[tuple[float, float, str]], palavras: list[Palavra], duracao: float,
                   op: OpcoesRevisao) -> list[Janela]:
    inicios = [p.inicio for p in palavras]
    pausas = _pausas(palavras, duracao)
    brutas: list[Janela] = []
    for a, b, motivo in sorted(alvos):
        wa, wb = max(0.0, a - op.contexto_janela), min(duracao, b + op.contexto_janela)
        falta = op.janela_minima - (wb - wa)
        if falta > 0:
            wa, wb = max(0.0, wa - falta / 2), min(duracao, wb + falta / 2)
        wa = max(0.0, _encaixar(wa, palavras, inicios, pausas, -1))
        wb = min(duracao, _encaixar(wb, palavras, inicios, pausas, +1))
        if wb > wa:
            brutas.append(Janela(wa, wb, {motivo}))
    brutas.sort(key=lambda j: j.inicio)
    unidas: list[Janela] = []
    for j in brutas:
        if unidas and j.inicio <= unidas[-1].fim + 0.3:
            ultima = unidas[-1]
            if max(ultima.fim, j.fim) - ultima.inicio <= op.janela_maxima:
                ultima.fim = max(ultima.fim, j.fim)
                ultima.motivos |= j.motivos
                continue
            j.inicio = max(j.inicio, ultima.fim)  # sem sobreposição entre janelas
            if j.fim - j.inicio < 0.3:
                ultima.motivos |= j.motivos
                continue
        unidas.append(j)
    # Janelas longas demais são divididas em pausas.
    finais: list[Janela] = []
    for j in unidas:
        ini = j.inicio
        while j.fim - ini > op.janela_maxima:
            corte_ideal = ini + op.janela_maxima - 2.0
            candidatas = [(a + b) / 2 for a, b in pausas if ini + op.janela_minima < (a + b) / 2 < ini + op.janela_maxima]
            corte = min(candidatas, key=lambda c: abs(c - corte_ideal)) if candidatas else ini + op.janela_maxima
            finais.append(Janela(ini, corte, set(j.motivos)))
            ini = corte
        finais.append(Janela(ini, j.fim, set(j.motivos)))
    return finais


def _hipotese_revisao(rec: Reconhecedor, audio: np.ndarray, da: float, db: float, prompt: str,
                      hotwords: str, op: OpcoesRevisao) -> list[Palavra]:
    trecho = audio[int(da * TAXA) : int(db * TAXA)]
    segs: list[SegmentoASR] = rec.transcrever(trecho, prompt=prompt, hotwords=hotwords, condicionar=False,
                                              beam=op.beam, paciencia=op.paciencia,
                                              temperaturas=(0.0, 0.2, 0.4, 0.6))
    saida: list[Palavra] = []
    for s in segs:
        tipo = assinatura_alucinacao(s.texto)
        if tipo == "forte":
            continue
        if tipo == "fraca" and (s.avg_logprob < -0.6 or s.no_speech_prob > 0.5):
            continue
        if prompt and eco_do_prompt(s.texto, prompt):
            continue
        for p in s.palavras:
            saida.append(Palavra(da + p.inicio, da + p.fim, p.texto, p.prob, origem="revisao"))
    return saida


def _prompt_revisao(rec: Reconhecedor, contexto: str | None, anteriores: list[Palavra]) -> str:
    partes = []
    if contexto and contexto.strip():
        c = contexto.strip()
        partes.append(c if c.endswith((".", "?", "!")) else c + ".")
    if anteriores:
        partes.append(juntar_palavras([p.texto for p in anteriores]))
    prompt = " ".join(partes)
    return rec.truncar_final(prompt, 150)


def revisar(
    rec: Reconhecedor,
    audio: np.ndarray,
    palavras: list[Palavra],
    alvos_segmentos: list[tuple[float, float, str]],
    fala_ref: list[Intervalo],
    hotwords: str,
    contexto: str | None,
    op: OpcoesRevisao,
    progresso: Callable[[float], None] | None = None,
    fala_total: list[Intervalo] | None = None,
) -> tuple[list[Palavra], list[Marcador], list[RegistroRevisao], dict]:
    """`fala_ref`: fala de referência para lacunas; `fala_total`: união de VAD e diarização,
    usada para reconhecer palavras ditas onde nenhum detector ouviu voz (alucinação)."""
    duracao = len(audio) / TAXA
    fala_total = fala_total if fala_total is not None else fala_ref
    palavras = sorted((copy.copy(p) for p in palavras), key=lambda p: (p.inicio, p.fim))
    votacao = OpcoesVotacao(op.prob_minima_manter, op.prob_minima_insercao, op.limiar_sem_maioria,
                            op.limiar_absoluto)

    alvos = list(alvos_segmentos)
    alvos += [(a, b, "palavras com baixa confiança") for a, b in
              unir(((p.inicio, p.fim) for p in palavras if _suspeita(rec, p, op)), tolerancia=1.0)]
    alvos += [(a, b, "resposta curta isolada") for a, b in _frases_curtas(palavras, op)]
    alvos += [(p.inicio, p.fim, "palavra fora da fala detectada") for p in palavras
              if evidencia_fala(p.inicio - 0.1, p.fim + 0.1, fala_total) < 0.2]
    vazias = lacunas(fala_ref, palavras, op.lacuna_minima)
    alvos += [(a, b, "fala detectada sem transcrição") for a, b in vazias]
    janelas = montar_janelas(alvos, palavras, duracao, op)
    log.debug("Revisão: %d alvos em %d janelas", len(alvos), len(janelas))

    registros: list[RegistroRevisao] = []
    incertezas: list[dict] = []
    descartadas: list[dict] = []
    estat = {"janelas": len(janelas), "alteradas": 0, "palavras_recuperadas": 0}
    for n, j in enumerate(janelas):
        wa, wb = j.inicio, j.fim
        meios = [p.meio for p in palavras]
        i_ini = bisect.bisect_left(meios, wa)
        i_fim = bisect.bisect_right(meios, wb)
        h1 = palavras[i_ini:i_fim]
        e_ini = bisect.bisect_left(meios, wa - 2.5)
        e_fim = bisect.bisect_right(meios, wb + 2.5)
        h1_ext = palavras[e_ini:e_fim]
        anteriores = palavras[max(0, i_ini - 40) : i_ini]

        # Hipótese 2: contexto da reunião (texto anterior) e feixe largo.
        prompt = _prompt_revisao(rec, contexto, anteriores)
        h2 = _recortar(_hipotese_revisao(rec, audio, max(0.0, wa - 0.4), min(duracao, wb + 0.4), prompt,
                                         hotwords, op), h1_ext, wa, wb)
        # Hipótese 3: sem prompt e com outra janela acústica (independente da 2).
        m = op.margem_alternativa
        h3 = _recortar(_hipotese_revisao(rec, audio, max(0.0, wa - 0.4 - m), min(duracao, wb + 0.4 + m), "",
                                         hotwords, replace(op, beam=5)), h1_ext, wa - 0.2, wb + 0.2)

        lacunas_janela = [x for x in vazias if x[1] > wa and x[0] < wb]
        base = h1
        if _degenerada(h1) and not _degenerada(h2):
            # Laço de repetição ou alucinação no 1º passo: o trecho é tratado como lacuna.
            base = []
            lacunas_janela = [(wa, wb)]
        novas, duvidas, fora = combinar(base, h2, h3, lacunas_janela, votacao, fala_total)
        incertezas.extend(d.para_dict() for d in duvidas)
        if fora:
            descartadas.append({"inicio": round(fora[0].inicio, 2), "fim": round(fora[-1].fim, 2),
                                "texto": juntar_palavras([p.texto for p in fora]),
                                "motivo": "não confirmadas pelas decodificações de revisão, com pouca fala "
                                          "detectada no trecho ou confiança baixa"})
        alterado = juntar_palavras([p.texto for p in novas]) != juntar_palavras([p.texto for p in h1]) or any(
            p.incerta for p in novas)
        estat["alteradas"] += int(alterado)
        estat["palavras_recuperadas"] += sum(1 for p in novas if p.origem == "recuperada")
        palavras[i_ini:i_fim] = novas
        palavras.sort(key=lambda p: (p.inicio, p.fim))
        registros.append(RegistroRevisao(
            wa, wb, sorted(j.motivos), alterado, juntar_palavras([p.texto for p in h1]),
            juntar_palavras([p.texto for p in h2]), juntar_palavras([p.texto for p in h3]),
            juntar_palavras([p.texto for p in novas]),
        ))
        if progresso:
            progresso((n + 1) / max(1, len(janelas)))

    marcadores = [Marcador(a, b, "inaudivel") for a, b in lacunas(fala_ref, palavras, op.inaudivel_minimo)]
    estat["inaudiveis"] = len(marcadores)
    estat["palavras_incertas"] = sum(1 for p in palavras if p.incerta)
    estat["incertezas"] = incertezas
    estat["descartadas"] = descartadas
    return palavras, marcadores, registros, estat


def _suspeita(rec: Reconhecedor, p: Palavra, op: OpcoesRevisao) -> bool:
    if p.prob < op.limiar_palavra:
        return True
    if p.prob < op.limiar_palavra_longa:
        nucleo = p.texto.strip().strip(".,;:!?…\"'()[]")
        return bool(nucleo) and rec.contar_tokens(nucleo) >= op.tokens_palavra_longa
    return False


def _frases_curtas(palavras: list[Palavra], op: OpcoesRevisao, pausa: float = 0.5) -> list[Intervalo]:
    """Frases de até 2 palavras, isoladas por pausas, com confiança abaixo do limiar."""
    grupos: list[list[Palavra]] = []
    for p in palavras:
        if grupos and p.inicio - grupos[-1][-1].fim < pausa and not termina_frase(grupos[-1][-1].texto):
            grupos[-1].append(p)
        else:
            grupos.append([p])
    alvos = []
    for i, g in enumerate(grupos):
        if len(g) > 2:
            continue
        antes = grupos[i - 1][-1].fim if i > 0 else -1e9
        depois = grupos[i + 1][0].inicio if i + 1 < len(grupos) else 1e9
        isolada = g[0].inicio - antes >= pausa * 0.6 or depois - g[-1].fim >= pausa * 0.6
        if isolada and sum(p.prob for p in g) / len(g) < op.limiar_frase_curta:
            alvos.append((g[0].inicio, g[-1].fim))
    return alvos


def _recortar(h: list[Palavra], h1_ext: list[Palavra], wa: float, wb: float) -> list[Palavra]:
    """Palavras da hipótese dentro da janela, sem as que repetem o contexto vizinho."""
    pares = pares_alinhados(h1_ext, h)
    fora = {k2 for k1, k2 in pares if not (wa <= h1_ext[k1].meio <= wb)}
    return [p for k, p in enumerate(h) if wa <= p.meio <= wb and k not in fora]


def _degenerada(h: list[Palavra]) -> bool:
    if not h:
        return False
    texto = " ".join(p.texto for p in h)
    return repeticao_excessiva(tokens(texto)) is not None or assinatura_alucinacao(texto) == "forte"
