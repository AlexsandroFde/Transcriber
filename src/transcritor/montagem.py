"""Atribuição de falantes às palavras e montagem dos blocos da transcrição.

Cada palavra recebe o falante cujo turno (diarização exclusiva) mais se sobrepõe a ela.
Atribuições "firmes" (palavra quase toda dentro de um turno) nunca são alteradas.
Atribuições "frágeis" (palavra na fronteira entre dois turnos, onde pequenas imprecisões
de tempo trocam o falante) são corrigidas apenas em padrões claros:
  * ilha: trecho curto de outro falante no meio de uma frase de um mesmo falante;
  * início ou fim de frase "vazando" para o turno vizinho.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from .intervalos import sobreposicao
from .modelos import Bloco, Marcador, Palavra, Trecho, Turno
from .texto import capitalizar_inicio, juntar_palavras, termina_frase

ROTULO_DESCONHECIDO = "Participante não identificado"


@dataclass
class OpcoesMontagem:
    max_bloco_s: float = 60.0  # parágrafo longo é quebrado no fim de frase após este tempo
    pausa_novo_bloco_s: float = 4.0  # pausa longa do mesmo falante abre novo parágrafo
    sobreposicao_minima_s: float = 0.6  # fala que começa sobre outra por pelo menos isto é marcada
    simultanea_minima_s: float = 1.0  # turno sem palavras, encoberto por outra fala, vira marcador
    firmeza_minima: float = 0.7
    distancia_maxima_s: float = 1.0


@dataclass
class _InfoAtribuicao:
    fracao: float = 0.0
    dur_turno: float = 0.0
    sobreposta: bool = False  # palavra dita enquanto duas ou mais pessoas falavam

    def firme(self, op: OpcoesMontagem) -> bool:
        return self.fracao >= op.firmeza_minima and self.dur_turno >= 0.3 and not self.sobreposta


def regioes_sobrepostas(turnos: list[Turno]) -> list[tuple[float, float]]:
    """Intervalos em que dois ou mais falantes diferentes estão ativos ao mesmo tempo."""
    eventos = sorted([(t.inicio, 1, t.falante) for t in turnos] + [(t.fim, -1, t.falante) for t in turnos],
                     key=lambda e: (e[0], e[1]))
    ativos: dict[str, int] = {}
    regioes: list[tuple[float, float]] = []
    inicio = None
    for tempo_, tipo, f in eventos:
        ativos[f] = ativos.get(f, 0) + tipo
        n = sum(1 for v in ativos.values() if v > 0)
        if n >= 2 and inicio is None:
            inicio = tempo_
        elif n < 2 and inicio is not None:
            if tempo_ > inicio:
                regioes.append((inicio, tempo_))
            inicio = None
    return regioes


def atribuir_falantes(palavras: list[Palavra], exclusivos: list[Turno], op: OpcoesMontagem,
                      turnos: list[Turno] | None = None) -> list[_InfoAtribuicao]:
    exc = sorted(exclusivos, key=lambda t: t.inicio)
    inicios = [t.inicio for t in exc]
    sobrepostas = regioes_sobrepostas(turnos or [])
    ini_sobre = [a for a, _ in sobrepostas]
    infos: list[_InfoAtribuicao] = []
    for p in palavras:
        dur = max(p.fim - p.inicio, 0.02)
        k_s = bisect.bisect_right(ini_sobre, p.fim)
        em_sobre = sum(sobreposicao((p.inicio, p.fim), sobrepostas[i]) for i in range(max(0, k_s - 3), k_s))
        sobreposta = em_sobre >= 0.5 * dur
        k = bisect.bisect_left(inicios, p.fim)
        por_falante: dict[str, float] = {}
        maior_turno: dict[str, float] = {}
        j = k - 1
        while j >= 0 and exc[j].fim > p.inicio:
            ov = sobreposicao((p.inicio, p.fim), (exc[j].inicio, exc[j].fim))
            if ov > 0:
                f = exc[j].falante
                por_falante[f] = por_falante.get(f, 0.0) + ov
                maior_turno[f] = max(maior_turno.get(f, 0.0), exc[j].duracao)
            j -= 1
        if por_falante:
            f = max(por_falante, key=lambda x: por_falante[x])
            p.falante = f
            infos.append(_InfoAtribuicao(min(1.0, por_falante[f] / dur), maior_turno[f], sobreposta))
            continue
        # Sem sobreposição: turno mais próximo, se estiver perto.
        candidatos = []
        if k - 1 >= 0:
            candidatos.append((p.inicio - exc[k - 1].fim, exc[k - 1]))
        if k < len(exc):
            candidatos.append((exc[k].inicio - p.fim, exc[k]))
        candidatos = [(d, t) for d, t in candidatos if d <= op.distancia_maxima_s]
        if candidatos:
            p.falante = min(candidatos, key=lambda x: x[0])[1].falante
        else:
            p.falante = None
        infos.append(_InfoAtribuicao(sobreposta=sobreposta))
    return infos


def _ativo_perto(falante: str | None, inicio: float, fim: float, turnos: list[Turno] | None,
                 tolerancia: float = 0.5) -> bool:
    """O falante tem turno (diarização com sobreposição) perto deste intervalo?"""
    if not turnos or falante is None:
        return True
    return any(t.falante == falante and t.inicio - tolerancia < fim and t.fim + tolerancia > inicio for t in turnos)


def _frases(palavras: list[Palavra], pausa: float = 1.0) -> list[list[int]]:
    frases: list[list[int]] = []
    atual: list[int] = []
    for i, p in enumerate(palavras):
        if atual and p.inicio - palavras[atual[-1]].fim >= pausa:
            frases.append(atual)
            atual = []
        atual.append(i)
        if termina_frase(p.texto):
            frases.append(atual)
            atual = []
    if atual:
        frases.append(atual)
    return frases


def _corridas(indices: list[int], palavras: list[Palavra]) -> list[list[int]]:
    corridas: list[list[int]] = []
    for i in indices:
        if corridas and palavras[corridas[-1][-1]].falante == palavras[i].falante:
            corridas[-1].append(i)
        else:
            corridas.append([i])
    return corridas


def suavizar(palavras: list[Palavra], infos: list[_InfoAtribuicao], op: OpcoesMontagem,
             turnos: list[Turno] | None = None) -> int:
    """Corrige atribuições frágeis em padrões claros. Retorna quantas palavras mudaram."""
    # Palavras sem falante herdam do vizinho mais próximo.
    for i, p in enumerate(palavras):
        if p.falante is None:
            antes = next((palavras[k] for k in range(i - 1, -1, -1) if palavras[k].falante), None)
            depois = next((palavras[k] for k in range(i + 1, len(palavras)) if palavras[k].falante), None)
            opcoes = [(p.inicio - a.fim, a.falante) for a in [antes] if a] + [(d.inicio - p.fim, d.falante) for d in [depois] if d]
            if opcoes:
                p.falante = min(opcoes)[1]
    mudancas = 0

    def fragil(corrida: list[int], max_dur: float = 1.5) -> bool:
        dur = palavras[corrida[-1]].fim - palavras[corrida[0]].inicio
        return dur <= max_dur and all(not infos[i].firme(op) for i in corrida)

    def mover(corrida: list[int], destino: str | None) -> int:
        ini, fim = palavras[corrida[0]].inicio, palavras[corrida[-1]].fim
        if not _ativo_perto(destino, ini, fim, turnos):
            return 0
        for i in corrida:
            palavras[i].falante = destino
        return len(corrida)

    for frase in _frases(palavras):
        corridas = _corridas(frase, palavras)
        if len(corridas) < 2:
            continue
        # Ilhas no meio da frase.
        for c in range(1, len(corridas) - 1):
            ant, atual, prox = corridas[c - 1], corridas[c], corridas[c + 1]
            f_ant = palavras[ant[0]].falante
            if f_ant == palavras[prox[0]].falante != palavras[atual[0]].falante and fragil(atual):
                mudancas += mover(atual, f_ant)
        corridas = _corridas(frase, palavras)
        if len(corridas) < 2:
            continue
        # Começo de frase vazando do turno anterior.
        primeira, segunda = corridas[0], corridas[1]
        if len(segunda) >= 2 and fragil(primeira):
            mudancas += mover(primeira, palavras[segunda[0]].falante)
        corridas = _corridas(frase, palavras)
        if len(corridas) < 2:
            continue
        # Fim de frase vazando para o turno seguinte.
        penultima, ultima = corridas[-2], corridas[-1]
        if len(penultima) >= 2 and fragil(ultima):
            mudancas += mover(ultima, palavras[penultima[0]].falante)
    return mudancas


def falante_em(inicio: float, fim: float, exclusivos: list[Turno]) -> str | None:
    melhor, valor = None, 0.0
    for t in exclusivos:
        ov = sobreposicao((inicio, fim), (t.inicio, t.fim))
        if ov > valor:
            melhor, valor = t.falante, ov
    return melhor


def marcadores_simultaneos(palavras: list[Palavra], turnos: list[Turno], op: OpcoesMontagem) -> list[Marcador]:
    """Turnos de um falante sem nenhuma palavra transcrita, encobertos pela fala de outro."""
    marcadores = []
    meios = [p.meio for p in palavras]
    for t in turnos:
        if t.duracao < op.simultanea_minima_s:
            continue
        a = bisect.bisect_left(meios, t.inicio)
        b = bisect.bisect_right(meios, t.fim)
        dentro = palavras[a:b]
        if not dentro or any(p.falante == t.falante for p in dentro):
            continue
        coberto = sum(min(p.fim, t.fim) - max(p.inicio, t.inicio) for p in dentro)
        if coberto >= 0.4 * t.duracao:
            marcadores.append(Marcador(t.inicio, t.fim, "simultanea", t.falante))
    return marcadores


def rotular(palavras: list[Palavra], marcadores: list[Marcador], turnos: list[Turno]) -> dict[str, str]:
    """'Participante N' na ordem em que cada voz aparece na transcrição."""
    ordem: list[str] = []
    for e in sorted([*palavras, *marcadores], key=lambda x: x.inicio):
        if e.falante and e.falante not in ordem:
            ordem.append(e.falante)
    for t in sorted(turnos, key=lambda x: x.inicio):
        if t.falante not in ordem:
            ordem.append(t.falante)
    return {f: f"Participante {i + 1}" for i, f in enumerate(ordem)}


def _texto_marcador(m: Marcador, exibir: dict[str, str]) -> str:
    if m.tipo == "inaudivel":
        return "[inaudível]"
    if m.tipo == "simultanea":
        return f"[falas simultâneas: {exibir.get(m.falante or '', ROTULO_DESCONHECIDO)}]"
    return f"[{m.tipo}]"


def _renderizar(elementos: list, exibir: dict[str, str]) -> list[Trecho]:
    trechos: list[Trecho] = []
    grupo: list[Palavra] = []
    incerto = False

    def fechar():
        nonlocal grupo
        if grupo:
            trechos.append(Trecho("incerto" if incerto else "texto", juntar_palavras([p.texto for p in grupo])))
            grupo = []

    for e in elementos:
        if isinstance(e, Marcador):
            fechar()
            trechos.append(Trecho("marcador", _texto_marcador(e, exibir)))
            continue
        if grupo and e.incerta != incerto:
            fechar()
        incerto = e.incerta
        grupo.append(e)
    fechar()
    # Maiúscula no início do parágrafo (ajuste tipográfico, não altera a fala).
    for t in trechos:
        if t.tipo in ("texto", "incerto"):
            t.texto = capitalizar_inicio(t.texto)
            break
    return trechos


def montar_blocos(
    palavras: list[Palavra],
    marcadores: list[Marcador],
    turnos: list[Turno],
    exibir: dict[str, str],
    op: OpcoesMontagem,
) -> list[Bloco]:
    """Agrupa palavras e marcadores em parágrafos por falante, com quebras por tempo/pausa."""

    def nome(f: str | None) -> str:
        return exibir.get(f, ROTULO_DESCONHECIDO) if f else ROTULO_DESCONHECIDO

    elementos = sorted([*palavras, *marcadores], key=lambda e: (e.inicio, 0 if isinstance(e, Marcador) else 1))
    grupos: list[tuple[str, list]] = []
    ultimo_fim = 0.0
    inicio_grupo = 0.0
    for e in elementos:
        anexar = isinstance(e, Marcador) and e.tipo == "simultanea"
        f = nome(e.falante)
        if grupos and anexar:
            grupos[-1][1].append(e)
            continue
        novo = not grupos or grupos[-1][0] != f
        if not novo:
            pausa = e.inicio - ultimo_fim
            anterior = grupos[-1][1][-1]
            fim_frase = isinstance(anterior, Marcador) or termina_frase(getattr(anterior, "texto", "."))
            if pausa >= op.pausa_novo_bloco_s or (e.inicio - inicio_grupo >= op.max_bloco_s and fim_frase):
                novo = True
        if novo:
            grupos.append((f, [e]))
            inicio_grupo = e.inicio
        else:
            grupos[-1][1].append(e)
        ultimo_fim = max(ultimo_fim, e.fim) if not novo else e.fim

    blocos: list[Bloco] = []
    for f, elems in grupos:
        principais = [e for e in elems if not (isinstance(e, Marcador) and e.tipo == "simultanea")] or elems
        ini = principais[0].inicio
        fim = max(e.fim for e in elems)
        bloco = Bloco(ini, fim, f, _renderizar(elems, exibir))
        bloco.sobreposto_a = _sobreposicao_no_inicio(f, ini, turnos, nome, op)
        blocos.append(bloco)
    return blocos


def _sobreposicao_no_inicio(f: str, ini: float, turnos: list[Turno], nome, op: OpcoesMontagem) -> list[str]:
    """Quem ainda estava falando quando este falante começou o turno.

    O início é medido pelo turno da diarização (as marcas de tempo das palavras tendem a
    "empurrar" a primeira palavra de uma interrupção para depois do fim da fala anterior).
    Só conta se o turno do falante começa perto do bloco (não é continuação de fala antiga).
    """
    proprios = [t for t in turnos if nome(t.falante) == f and ini - 1.5 <= t.inicio <= ini + 0.5 and t.fim >= ini]
    t0 = min((t.inicio for t in proprios), default=ini)
    outros = {nome(t.falante) for t in turnos
              if nome(t.falante) != f and t.inicio < t0 - 0.1 and t.fim > t0 + op.sobreposicao_minima_s}
    return sorted(outros)


def texto_bloco(bloco: Bloco, incluir_sobreposicao: bool = True) -> str:
    """Texto corrido de um bloco, com marcadores e trechos incertos sinalizados."""
    partes: list[str] = []
    if incluir_sobreposicao and bloco.sobreposto_a:
        partes.append(f"[falas simultâneas com {', '.join(bloco.sobreposto_a)}]")
    for t in bloco.trechos:
        if t.tipo == "incerto":
            interno = t.texto.rstrip(".,;:!?…")
            sufixo = t.texto[len(interno):]
            partes.append(f"[trecho incerto: {interno}]{sufixo}")
        else:
            partes.append(t.texto)
    return " ".join(p for p in partes if p).strip()
