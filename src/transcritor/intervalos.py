"""Operações sobre listas de intervalos de tempo (início, fim) em segundos."""

from __future__ import annotations

from collections.abc import Iterable

Intervalo = tuple[float, float]


def unir(intervalos: Iterable[Intervalo], tolerancia: float = 0.0) -> list[Intervalo]:
    """Ordena e funde intervalos que se sobrepõem ou distam até `tolerancia` segundos."""
    ordenados = sorted((float(a), float(b)) for a, b in intervalos if b > a)
    resultado: list[Intervalo] = []
    for a, b in ordenados:
        if resultado and a <= resultado[-1][1] + tolerancia:
            if b > resultado[-1][1]:
                resultado[-1] = (resultado[-1][0], b)
        else:
            resultado.append((a, b))
    return resultado


def subtrair(base: Iterable[Intervalo], remover: Iterable[Intervalo]) -> list[Intervalo]:
    """Retorna as partes de `base` que não estão cobertas por `remover`."""
    base_u = unir(base)
    rem_u = unir(remover)
    resultado: list[Intervalo] = []
    j = 0
    for a, b in base_u:
        atual = a
        while j < len(rem_u) and rem_u[j][1] <= atual:
            j += 1
        k = j
        while k < len(rem_u) and rem_u[k][0] < b:
            ra, rb = rem_u[k]
            if ra > atual:
                resultado.append((atual, min(ra, b)))
            atual = max(atual, rb)
            if atual >= b:
                break
            k += 1
        if atual < b:
            resultado.append((atual, b))
    return resultado


def sobreposicao(a: Intervalo, b: Intervalo) -> float:
    """Duração da interseção entre dois intervalos."""
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def sobreposicao_total(alvo: Intervalo, intervalos: Iterable[Intervalo]) -> float:
    """Soma das interseções de `alvo` com uma lista de intervalos (assumidos disjuntos)."""
    return sum(sobreposicao(alvo, i) for i in intervalos)


def expandir(intervalos: Iterable[Intervalo], margem: float, limite: float | None = None) -> list[Intervalo]:
    """Expande cada intervalo por `margem` dos dois lados, limitado a [0, limite]."""
    saida = []
    for a, b in intervalos:
        na = max(0.0, a - margem)
        nb = b + margem
        if limite is not None:
            nb = min(limite, nb)
        if nb > na:
            saida.append((na, nb))
    return saida


def duracao_total(intervalos: Iterable[Intervalo]) -> float:
    return sum(b - a for a, b in unir(intervalos))


def filtrar_minimo(intervalos: Iterable[Intervalo], duracao_minima: float) -> list[Intervalo]:
    return [(a, b) for a, b in intervalos if b - a >= duracao_minima]
