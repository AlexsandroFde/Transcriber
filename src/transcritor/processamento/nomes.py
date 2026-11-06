"""Sugestões de nomes para os participantes, baseadas apenas em evidências explícitas na fala.

Nenhum nome é aplicado automaticamente: as sugestões vão para o relatório e só passam a
valer quando a pessoa usuária confirma com o comando `transcritor nomear`.

Evidências diretas (autoidentificação): "meu nome é Ana", "aqui é o Carlos", "sou a Beatriz".
Evidências indiretas (mais fracas), a partir de vocativos:
  * reação, agradecimento ou cumprimento dirigido a alguém ("Obrigado, Ana.",
    "Bem lembrado, Carlos.", "Bom dia, Mariana.") sugere que essa pessoa acabou de falar;
  * pergunta ou pedido dirigido a alguém ("Carlos, você pode...?", "Juliana, como está...?",
    "passo a palavra para a Ana") sugere que essa pessoa fala em seguida.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MAIUSC = "A-ZÁÉÍÓÚÂÊÔÃÕÇÀ"
_MINUSC = "a-záéíóúâêôãõçàü"
NOME = rf"(?P<nome>[{_MAIUSC}][{_MINUSC}]+(?:\s+(?:d[aeo]s?\s+)?[{_MAIUSC}][{_MINUSC}]+){{0,3}})"
_FIM = r"(?=[\s,.!?…]|$)"

_NAO_NOMES = {
    "então", "bom", "boa", "tá", "olha", "gente", "pessoal", "sim", "não", "obrigado", "obrigada", "ok",
    "beleza", "certo", "claro", "isso", "aqui", "agora", "depois", "também", "mas", "e", "é", "eu", "você",
    "vocês", "ele", "ela", "nós", "a", "o", "os", "as", "um", "uma", "senhor", "senhora", "professor",
    "professora", "doutor", "doutora", "dona", "seu", "deus", "nossa", "tchau", "oi", "olá", "alô", "pois",
    "enfim", "assim", "aí", "lá", "ah", "hum", "eh", "né", "bem", "ótimo", "perfeito", "exato", "exatamente",
    "verdade", "pronto", "vamos", "vou", "vai", "tudo", "todos", "todas", "dia", "tarde", "noite", "reunião",
    "como", "qual", "quando", "onde", "quem", "porque", "por", "para", "pra", "se", "que", "mais", "muito",
    "quer", "sabe", "veja", "vejam", "escuta", "espera", "desculpa", "desculpe", "inclusive", "aliás",
    "primeiro", "segundo", "outra", "outro", "imagina", "lembra", "entendeu", "entende", "galera", "turma",
    "time", "equipe", "minha", "meu", "nosso", "caro", "cara", "amigo", "amiga", "colega", "colegas",
}

_DIRETAS = [
    re.compile(rf"\b[Mm]eu nome (?:é|eh) {NOME}"),
    re.compile(rf"\b[Mm]e chamo {NOME}"),
    re.compile(rf"\b(?:[Ee]u )?sou (?:o|a) {NOME}{_FIM}"),
    re.compile(rf"\b[Aa]qui (?:é|quem fala é) (?:o |a )?{NOME}"),
    re.compile(rf"\b(?:é|eh) (?:o|a) {NOME},? (?:falando|aqui falando)\b"),
    re.compile(rf"^{NOME},? (?:falando|aqui falando)\b"),
]
_REACAO = (r"(?:[Oo]brigad[oa]|[Vv]aleu|[Bb]rigad[oa]|[Bb]em lembrado|[Bb]oa|[Óó]timo|[Pp]erfeito|[Ee]xato|"
           r"[Ee]xatamente|[Ii]sso mesmo|[Cc]oncordo|[Cc]erto|[Bb]eleza|[Bb]om dia|[Bb]oa tarde|[Bb]oa noite|"
           r"[Oo]i|[Oo]lá)")
_PARA_ANTERIOR = re.compile(rf"\b{_REACAO},? {NOME}[.!]?(?:\s|$)")
_PARA_PROXIMO = [
    re.compile(rf"^{NOME}, (?:você|vc|tu|pode|poderia|quer|gostaria|consegue|por favor)\b"),
    re.compile(rf"^{NOME}, .*\?$"),
    re.compile(rf", {NOME}\?$"),
    re.compile(rf"\bpasso a palavra (?:para|pro|pra|à|ao) (?:o |a )?{NOME}"),
    re.compile(rf"\b[Cc]om a palavra,? (?:o |a )?{NOME}"),
]


def _valido(nome: str) -> bool:
    return nome.split()[0].lower() not in _NAO_NOMES and len(nome) >= 3


@dataclass
class Evidencia:
    falante: str  # identificador bruto do falante a quem o nome é sugerido
    nome: str
    tipo: str  # "direta" | "indireta"
    tempo: float
    trecho: str


def sugerir(frases: list[tuple[float, float, str | None, str]], janela: float = 5.0) -> list[Evidencia]:
    """`frases`: (início, fim, falante bruto, texto) em ordem cronológica.

    Indícios indiretos só valem se a fala da outra pessoa estiver colada (até `janela`
    segundos) à frase com o nome; caso contrário, a ligação entre nome e voz é fraca demais.
    """
    evidencias: list[Evidencia] = []
    for i, (t, fim, falante, texto) in enumerate(frases):
        if not falante:
            continue
        texto = texto.strip()
        for rx in _DIRETAS:
            for m in rx.finditer(texto):
                if _valido(m.group("nome")):
                    evidencias.append(Evidencia(falante, m.group("nome"), "direta", t, texto))
        m = _PARA_ANTERIOR.search(texto)
        if m and _valido(m.group("nome")):
            anterior = next(((f, f_fim) for _, f_fim, f, _ in reversed(frases[:i]) if f and f != falante), None)
            if anterior and t - anterior[1] <= janela:
                evidencias.append(Evidencia(anterior[0], m.group("nome"), "indireta", t, texto))
        for rx in _PARA_PROXIMO:
            m = rx.search(texto)
            if m and _valido(m.group("nome")):
                proximo = next(((f, f_ini) for f_ini, _, f, _ in frases[i + 1 :] if f and f != falante), None)
                if proximo and proximo[1] - fim <= janela:
                    evidencias.append(Evidencia(proximo[0], m.group("nome"), "indireta", t, texto))
                break
    return evidencias


def agrupar(evidencias: list[Evidencia]) -> dict[str, list[tuple[str, int, int, list[Evidencia]]]]:
    """Por falante: [(nome, nº de evidências diretas, nº de indiretas, exemplos)], mais citado primeiro."""
    por_falante: dict[str, dict[str, list[Evidencia]]] = {}
    for e in evidencias:
        por_falante.setdefault(e.falante, {}).setdefault(e.nome, []).append(e)
    saida = {}
    for f, nomes in por_falante.items():
        itens = []
        for nome, es in nomes.items():
            diretas = sum(1 for e in es if e.tipo == "direta")
            itens.append((nome, diretas, len(es) - diretas, sorted(es, key=lambda e: e.tipo != "direta")))
        itens.sort(key=lambda x: (-x[1], -x[2]))
        saida[f] = itens
    return saida
