"""Heurísticas de qualidade da transcrição.

Nada aqui reescreve fala. As funções apenas:
  * identificam segmentos suspeitos (alucinação, laço de repetição, confiança baixa),
    que são enviados para nova decodificação na etapa de revisão;
  * comparam hipóteses alternativas do mesmo trecho de áudio;
  * decidem quais palavras devem ser sinalizadas como incertas.
"""

from __future__ import annotations

import copy
import difflib
import math
import re
from dataclasses import dataclass, field

from .intervalos import Intervalo, sobreposicao_total, unir
from .modelos import Palavra, SegmentoASR
from .texto import juntar_palavras, normalizar, tokens

# ---------------------------------------------------------------------------
# Alucinações conhecidas do Whisper em português (legendas de vídeos da internet
# presentes nos dados de treino). Fortes: praticamente nunca são fala real numa reunião.
# ---------------------------------------------------------------------------
_ASSINATURAS_FORTES = [
    r"amara\s*\.?\s*org",
    r"legendas?\s+(pela|por|da)\s+comunidade",
    r"legendad[oa]s?\s+por",
    r"\blegendas?\s*:",
    r"\bzanotto\b",
    r"(transcri[cç][aã]o|tradu[cç][aã]o|revis[aã]o)\s+e\s+legendas",
    r"inscrev[ae]-se\s+(no|em\s+nosso|no\s+nosso)\s+canal",
    r"se\s+inscrev[ae]m?\s+(no|em\s+nosso|no\s+nosso)\s+canal",
    r"deix[ae]m?\s+(o\s+)?seu\s+like",
    r"ativ[ae]m?\s+o\s+sininho",
    r"sous[\s-]titres",
    r"subt[ií]tulos\s+(realizados|por|de)",
    r"www\.[a-z0-9-]+\.[a-z]{2,}",
    r"obrigad[oa]s?\s+por\s+assistir",
    r"at[eé]\s+o\s+pr[oó]ximo\s+v[ií]deo",
    r"compartilhe\s+(esse|este)\s+v[ií]deo",
]
# Fracas: podem ser fala real; só são descartadas quando há pouca evidência acústica.
_ASSINATURAS_FRACAS = [
    r"^(tchau[\s,.!]*)+$",
    r"^obrigad[oa]s?[\s.!]*$",
    r"^valeu[\s.!]*$",
    r"^at[eé]\s+(a\s+)?pr[oó]xima[\s.!]*$",
    r"^(\.|…|\s)+$",
    r"^\[?\(?(m[uú]sica|aplausos|risos|sil[eê]ncio)\)?\]?[\s.!]*$",
    r"^[♪♫\s]+$",
]
_RE_FORTES = [re.compile(p, re.IGNORECASE) for p in _ASSINATURAS_FORTES]
_RE_FRACAS = [re.compile(p, re.IGNORECASE) for p in _ASSINATURAS_FRACAS]


def assinatura_alucinacao(texto: str) -> str | None:
    """Retorna 'forte', 'fraca' ou None conforme o texto case com padrões conhecidos."""
    t = texto.strip()
    if any(r.search(t) for r in _RE_FORTES):
        return "forte"
    if any(r.search(t) for r in _RE_FRACAS):
        return "fraca"
    return None


def evidencia_fala(inicio: float, fim: float, fala: list[Intervalo]) -> float:
    """Fração do intervalo coberta por fala detectada (VAD/diarização)."""
    dur = max(1e-6, fim - inicio)
    return min(1.0, sobreposicao_total((inicio, fim), fala) / dur)


def eco_do_prompt(texto: str, prompt: str) -> bool:
    """Detecta quando o modelo apenas repetiu um pedaço do prompt (alucinação clássica)."""
    t = normalizar(texto)
    p = normalizar(prompt)
    if not t or not p or len(t) < 6:
        return False
    if t in p:
        return True
    sm = difflib.SequenceMatcher(a=t, b=p, autojunk=False)
    bloco = sm.find_longest_match(0, len(t), 0, len(p))
    return bloco.size >= 0.85 * len(t)


@dataclass
class Diagnostico:
    descartar: bool = False
    revisar: bool = False
    motivos: list[str] = field(default_factory=list)


def repeticao_excessiva(toks: list[str]) -> tuple[int, int, int] | None:
    """Procura n-gramas repetidos consecutivamente além do plausível.

    Retorna (posição, n, repetições) do pior caso, ou None.
    Limiares: palavra isolada repetida 6+ vezes; expressão de 2 a 6 palavras 3+ vezes.
    """
    pior = None
    for n in range(1, 7):
        limite = 6 if n == 1 else 3
        i = 0
        while i + 2 * n <= len(toks):
            reps = 1
            j = i + n
            while j + n <= len(toks) and toks[j : j + n] == toks[i : i + n]:
                reps += 1
                j += n
            if reps >= limite and (pior is None or reps * n > pior[2] * pior[1]):
                pior = (i, n, reps)
            i = j if reps > 1 else i + 1
    return pior


def diagnosticar_segmento(
    seg: SegmentoASR,
    fala: list[Intervalo],
    prompt: str = "",
    limiar_logprob: float = -0.7,
    limiar_prob_media: float = 0.55,
    max_palavras_por_segundo: float = 5.5,
) -> Diagnostico:
    """Classifica um segmento do primeiro passo: manter, revisar ou descartar."""
    d = Diagnostico()
    texto = seg.texto.strip()
    if not texto or not seg.palavras:
        d.descartar = True
        d.motivos.append("vazio")
        return d

    evid = evidencia_fala(seg.inicio, seg.fim, fala) if fala else 1.0
    tipo = assinatura_alucinacao(texto)
    if tipo == "forte":
        if not (evid >= 0.8 and seg.avg_logprob >= -0.3 and seg.no_speech_prob < 0.2):
            d.descartar = True
            d.motivos.append("frase típica de alucinação (legendas/vídeos)")
            return d
        d.revisar = True
        d.motivos.append("frase típica de alucinação mantida por evidência acústica forte")
    elif tipo == "fraca":
        if evid < 0.3 or (seg.no_speech_prob > 0.5 and seg.avg_logprob < -0.6):
            d.descartar = True
            d.motivos.append("frase curta típica de alucinação sem evidência de fala")
            return d

    if prompt and eco_do_prompt(texto, prompt) and seg.avg_logprob < -0.4:
        d.descartar = True
        d.motivos.append("repetição do texto de contexto (prompt)")
        return d

    if evid < 0.15 and seg.no_speech_prob > 0.6:
        d.descartar = True
        d.motivos.append("sem fala detectada no intervalo")
        return d

    toks = tokens(texto)
    if repeticao_excessiva(toks):
        d.revisar = True
        d.motivos.append("repetição em laço")
    dur = max(0.1, seg.fim - seg.inicio)
    if dur >= 2.0 and len(toks) / dur > max_palavras_por_segundo:
        d.revisar = True
        d.motivos.append("taxa de fala implausível")
    if seg.compression_ratio > 2.4:
        d.revisar = True
        d.motivos.append("texto muito repetitivo (compressão alta)")
    if seg.avg_logprob < limiar_logprob:
        d.revisar = True
        d.motivos.append("confiança média baixa")
    probs = [p.prob for p in seg.palavras]
    if probs and sum(probs) / len(probs) < limiar_prob_media:
        d.revisar = True
        d.motivos.append("probabilidade média das palavras baixa")
    if any(p.fim - p.inicio > 3.0 for p in seg.palavras):
        d.revisar = True
        d.motivos.append("duração de palavra anômala")
    return d


def intervalos_baixa_confianca(palavras: list[Palavra], limiar: float = 0.4) -> list[Intervalo]:
    """Intervalos de palavras com probabilidade abaixo do limiar (unidas se próximas)."""
    return unir(((p.inicio, p.fim) for p in palavras if p.prob < limiar), tolerancia=1.0)


# ---------------------------------------------------------------------------
# Comparação de hipóteses
# ---------------------------------------------------------------------------


def chave(p: Palavra) -> str:
    return normalizar(p.texto)


def pares_alinhados(h1: list[Palavra], h2: list[Palavra]) -> list[tuple[int, int]]:
    """Pares (i, j) de palavras coincidentes entre as hipóteses, em ordem."""
    k1 = [chave(p) for p in h1]
    k2 = [chave(p) for p in h2]
    sm = difflib.SequenceMatcher(a=k1, b=k2, autojunk=False)
    pares = []
    for bloco in sm.get_matching_blocks():
        for i in range(bloco.size):
            if k1[bloco.a + i]:
                pares.append((bloco.a + i, bloco.b + i))
    return pares


def alinhar(h1: list[Palavra], h2: list[Palavra]) -> tuple[set[int], set[int]]:
    """Índices das palavras de h1 e de h2 que coincidem no alinhamento."""
    pares = pares_alinhados(h1, h2)
    return {i for i, _ in pares}, {j for _, j in pares}


def similaridade(h1: list[Palavra], h2: list[Palavra]) -> float:
    k1 = [chave(p) for p in h1 if chave(p)]
    k2 = [chave(p) for p in h2 if chave(p)]
    if not k1 and not k2:
        return 1.0
    return difflib.SequenceMatcher(a=k1, b=k2, autojunk=False).ratio()


def pontuacao(h: list[Palavra]) -> float:
    """Média do log da probabilidade por palavra (maior é melhor)."""
    if not h:
        return -10.0
    return sum(math.log(max(p.prob, 1e-4)) for p in h) / len(h)


def cobertura(h: list[Palavra], fala: list[Intervalo], janela: Intervalo) -> float:
    """Fração da fala detectada dentro da janela que está coberta por palavras."""
    fala_janela = [(max(a, janela[0]), min(b, janela[1])) for a, b in fala if b > janela[0] and a < janela[1]]
    total = sum(b - a for a, b in fala_janela)
    if total <= 0:
        return 1.0 if h else 0.0
    cob = unir(((p.inicio - 0.1, p.fim + 0.1) for p in h))
    coberto = sum(sobreposicao_total(f, cob) for f in fala_janela)
    return min(1.0, coberto / total)


@dataclass
class Decisao:
    escolhida: str  # "passo1" | "revisao"
    motivo: str
    similaridade: float
    pontuacao1: float
    pontuacao2: float
    cobertura1: float
    cobertura2: float


def escolher(
    h1: list[Palavra],
    h2: list[Palavra],
    fala: list[Intervalo],
    janela: Intervalo,
    margem_pontuacao: float = 0.05,
) -> Decisao:
    """Escolhe entre a hipótese do primeiro passo (h1) e a da revisão (h2)."""
    s1, s2 = pontuacao(h1), pontuacao(h2)
    c1, c2 = cobertura(h1, fala, janela), cobertura(h2, fala, janela)
    sim = similaridade(h1, h2)
    t1 = " ".join(p.texto for p in h1)
    t2 = " ".join(p.texto for p in h2)
    laco1 = repeticao_excessiva(tokens(t1)) is not None
    laco2 = repeticao_excessiva(tokens(t2)) is not None
    aluc1 = assinatura_alucinacao(t1) == "forte"
    aluc2 = assinatura_alucinacao(t2) == "forte"

    def dec(qual: str, motivo: str) -> Decisao:
        return Decisao(qual, motivo, sim, s1, s2, c1, c2)

    if not h2:
        return dec("passo1", "revisão não produziu texto")
    if not h1:
        return dec("revisao", "primeiro passo não tinha texto neste trecho")
    if (laco1 or aluc1) and not (laco2 or aluc2) and c2 >= 0.5 * c1:
        return dec("revisao", "primeiro passo com repetição em laço ou alucinação")
    if (laco2 or aluc2) and not (laco1 or aluc1):
        return dec("passo1", "revisão com repetição em laço ou alucinação")
    # Nunca trocar por uma hipótese que cobre bem menos fala (evita omitir trechos).
    if c2 < 0.85 * c1:
        return dec("passo1", "revisão cobre menos fala")
    if c1 < 0.85 * c2:
        return dec("revisao", "primeiro passo omitiu parte da fala")
    if s2 > s1 + margem_pontuacao:
        return dec("revisao", "revisão com confiança maior")
    return dec("passo1", "primeiro passo mantido (confiança igual ou maior)")


def _comparavel(p: Palavra) -> str:
    """Chave de comparação; trata '%' e 'por cento' como a mesma coisa."""
    return chave(p).replace("%", " por cento").strip()


def _texto_norm(h: list[Palavra]) -> str:
    return " ".join(k for k in (_comparavel(p) for p in h) if k)


def _media_prob(h: list[Palavra]) -> float:
    return sum(p.prob for p in h) / len(h) if h else 0.0


@dataclass
class OpcoesVotacao:
    prob_minima_manter: float = 0.4  # palavra do 1º passo contestada só é descartada abaixo disto
    prob_minima_insercao: float = 0.4  # texto novo em lacuna, sem confirmação, precisa disto
    limiar_sem_maioria: float = 0.85  # sem maioria, palavras abaixo disto ficam incertas
    limiar_absoluto: float = 0.15  # mesmo confirmada, palavra abaixo disto fica incerta


@dataclass
class Incerteza:
    """Trecho sem maioria entre as decodificações, com as alternativas ouvidas."""

    inicio: float
    fim: float
    escolhido: str
    alternativas: list[str]

    def para_dict(self) -> dict:
        return {"inicio": round(self.inicio, 2), "fim": round(self.fim, 2), "escolhido": self.escolhido,
                "alternativas": self.alternativas}


def _regioes(k1: list[str], k2: list[str], max_igual: int = 3) -> list[tuple[str, int, int, int, int]]:
    """Regiões do alinhamento de h1 com h2.

    Além de 'equal', 'replace', 'insert' e 'delete', marca como 'equivalente' sequências de
    regiões vizinhas cujo texto é idêntico quando se ignoram os espaços ("a gente" x "agente",
    "e-mail" x "email"). Isso cobre os casos em que uma expressão repetida faz o alinhamento
    por palavras partir a diferença em pedaços distantes.
    """
    ops = difflib.SequenceMatcher(a=k1, b=k2, autojunk=False).get_opcodes()
    saida: list[tuple[str, int, int, int, int]] = []
    k = 0
    while k < len(ops):
        tag, i1, _i2, j1, _j2 = ops[k]
        if tag == "equal":
            saida.append(ops[k])
            k += 1
            continue
        achou = None
        for m in range(k, min(len(ops), k + 5)):
            if ops[m][0] == "equal":
                if ops[m][2] - ops[m][1] > max_igual:
                    break
                continue
            s1 = "".join(k1[i1 : ops[m][2]]).replace(" ", "")
            s2 = "".join(k2[j1 : ops[m][4]]).replace(" ", "")
            if s1 and s1 == s2:
                achou = m
                break
        if achou is None:
            saida.append(ops[k])
            k += 1
        else:
            saida.append(("equivalente", i1, ops[achou][2], j1, ops[achou][4]))
            k = achou + 1
    return saida


def combinar(
    h1: list[Palavra],
    h2: list[Palavra],
    h3: list[Palavra],
    lacunas: list[Intervalo] | None = None,
    op: OpcoesVotacao | None = None,
    fala: list[Intervalo] | None = None,
) -> tuple[list[Palavra], list[Incerteza], list[Palavra]]:
    """Combina três hipóteses do mesmo trecho, palavra a palavra, por maioria.

    h1: primeiro passo; h2: revisão com contexto; h3: revisão com outra janela acústica.
    h1 e h2 são alinhadas; em cada região divergente, h3 (também alinhada) desempata:
      * Diferença só de grafia, com os mesmos sons ("a gente" x "agente"): fica h1, que foi
        decodificada com o contexto mais longo.
      * h3 confirma h1 ou h2: vence a confirmada, sem sinalização.
      * h2 e h3 omitem palavras que h1 tem: as palavras ficam, sinalizadas como incertas, a
        menos que a confiança seja baixa ou não haja fala detectada no trecho; nesse caso saem
        do texto e entram na lista de descartadas (vão para o relatório). Nada some sem aviso.
      * Só h2 tem a palavra (fora de lacunas) e h3 não confirma: é descartada.
      * Em lacunas (trecho que o 1º passo pulou), votam só h2 e h3; sem confirmação, o texto
        entra sinalizado como incerto, se tiver probabilidade mínima.
      * Sem maioria: entra a hipótese mais provável, sinalizada como incerta.
    Retorna (palavras, incertezas, palavras descartadas).
    """
    op = op or OpcoesVotacao()
    descartadas: list[Palavra] = []
    lacunas = lacunas or []
    k1 = [_comparavel(p) for p in h1]
    k2 = [_comparavel(p) for p in h2]
    pares13 = pares_alinhados(h1, h3)
    confirmadas1 = {i for i, _ in pares13}
    confirmadas2 = {i for i, _ in pares_alinhados(h2, h3)}
    saida: list[Palavra] = []
    incertezas: list[Incerteza] = []

    def trecho_h3(i1: int, i2: int) -> list[Palavra]:
        """Palavras de h3 entre as âncoras (palavras alinhadas) que cercam h1[i1:i2]."""
        antes = max((j for i, j in pares13 if i < i1), default=-1)
        depois = min((j for i, j in pares13 if i >= i2), default=len(h3))
        return h3[antes + 1 : depois]

    def adicionar(ps: list[Palavra], incerta_se_abaixo: float | None, origem: str | None = None) -> list[Palavra]:
        novas = []
        for p in ps:
            q = copy.copy(p)
            if origem:
                q.origem = origem
            q.incerta = (incerta_se_abaixo is not None and q.prob < incerta_se_abaixo) or q.prob < op.limiar_absoluto
            novas.append(q)
        saida.extend(novas)
        return novas

    def registrar(escolhidas: list[Palavra], ini: float, fim: float, alternativas: list[list[Palavra]]) -> None:
        if not any(q.incerta for q in escolhidas):
            return
        escolhido = juntar_palavras([q.texto for q in escolhidas])
        alts = []
        for h in alternativas:
            t = juntar_palavras([q.texto for q in h]) if h else "(nenhuma palavra)"
            if normalizar(t) != normalizar(escolhido) and t not in alts:
                alts.append(t)
        incertezas.append(Incerteza(ini, fim, escolhido, alts))

    def fracao(ini: int, fim: int, confirmadas: set[int]) -> float:
        return sum(1 for i in range(ini, fim) if i in confirmadas) / (fim - ini) if fim > ini else 0.0

    for tag, i1, i2, j1, j2 in _regioes(k1, k2):
        a, b = h1[i1:i2], h2[j1:j2]
        if tag == "equal":
            for x, y in zip(a, b):
                q = copy.copy(x)
                q.prob = max(x.prob, y.prob)
                q.incerta = q.prob < op.limiar_absoluto
                saida.append(q)
            continue
        if tag == "equivalente":
            adicionar(a, None)  # mesma sequência de sons, grafia diferente: fica o 1º passo
            continue
        t1, t2 = _texto_norm(a), _texto_norm(b)
        if not t1 and not t2:
            adicionar(a, None)  # só pontuação
            continue
        todos = a + b
        ini = min(p.inicio for p in todos)
        fim = max(p.fim for p in todos)
        c = trecho_h3(i1, i2)
        s1 = fracao(i1, i2, confirmadas1)
        s2 = fracao(j1, j2, confirmadas2)
        em_lacuna = bool(lacunas) and sobreposicao_total((ini, fim), lacunas) >= 0.5 * max(fim - ini, 1e-6)
        if not t1 and em_lacuna:
            # O 1º passo pulou este trecho: votam só as duas revisões.
            if s2 >= 0.5:
                adicionar(b, None, "recuperada")
            elif _media_prob(b) >= op.prob_minima_insercao:
                registrar(adicionar(b, op.limiar_sem_maioria, "recuperada"), ini, fim, [c])
            continue
        if a and b:
            if s1 >= 0.5 and s1 > s2:
                adicionar(a, None)
            elif s2 >= 0.5 and s2 > s1:
                adicionar(b, None, "revisao")
            elif pontuacao(a) >= pontuacao(b):
                registrar(adicionar(a, op.limiar_sem_maioria), ini, fim, [b, c])
            else:
                registrar(adicionar(b, op.limiar_sem_maioria, "revisao"), ini, fim, [a, c])
        elif a:
            # A revisão com contexto não ouviu estas palavras.
            if s1 >= 0.5:
                adicionar(a, None)
            elif (fala is not None and evidencia_fala(ini, fim, fala) < 0.5) or _media_prob(a) < op.prob_minima_manter:
                # Duas decodificações contra uma, e pouca evidência acústica ou confiança baixa:
                # sai do texto, mas fica registrado no relatório de conferência.
                descartadas.extend(a)
            else:
                registrar(adicionar(a, 1.01), ini, fim, [b, c])
        elif s2 >= 0.5:
            adicionar(b, None, "recuperada")  # h2 e h3 ouviram algo que o 1º passo omitiu
    return saida, incertezas, descartadas


def marcar_incertas(
    escolhida: list[Palavra],
    alternativa: list[Palavra],
    limiar_discordancia: float = 0.6,
    limiar_absoluto: float = 0.15,
) -> None:
    """Sinaliza como incertas as palavras sem confirmação da hipótese alternativa.

    Uma palavra é incerta quando:
      * a hipótese alternativa não a confirma e sua probabilidade é < limiar_discordancia; ou
      * sua probabilidade é extremamente baixa (< limiar_absoluto), mesmo se confirmada.
    """
    confirmadas, _ = alinhar(escolhida, alternativa)
    for i, p in enumerate(escolhida):
        if not chave(p):
            continue
        if i not in confirmadas and p.prob < limiar_discordancia:
            p.incerta = True
        elif p.prob < limiar_absoluto:
            p.incerta = True


def termos_da_reuniao(palavras: list[Palavra], minimo_ocorrencias: int = 2, prob_minima: float = 0.6) -> list[str]:
    """Extrai nomes próprios, siglas e termos com números reconhecidos com segurança.

    Servem como vocabulário de apoio na revisão (contexto da própria reunião).
    """
    contagem: dict[str, list[float]] = {}
    anterior_fim_frase = True
    for p in palavras:
        bruto = p.texto.strip()
        limpo = bruto.strip(".,;:!?…\"'()[]{}")
        candidato = False
        if len(limpo) >= 2:
            if limpo.isupper() and any(c.isalpha() for c in limpo):
                candidato = True  # sigla
            elif limpo[0].isupper() and not anterior_fim_frase:
                candidato = True  # nome próprio no meio da frase
            elif any(c.isdigit() for c in limpo) and any(c.isalpha() for c in limpo):
                candidato = True  # termo alfanumérico (ex.: "ISO9001", "4G")
        if candidato:
            contagem.setdefault(limpo, []).append(p.prob)
        anterior_fim_frase = bruto.endswith((".", "?", "!", "…"))
    termos = [
        (t, len(ps)) for t, ps in contagem.items() if len(ps) >= minimo_ocorrencias and sum(ps) / len(ps) >= prob_minima
    ]
    termos.sort(key=lambda x: -x[1])
    return [t for t, _ in termos]
