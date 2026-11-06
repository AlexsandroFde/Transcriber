"""Relatório de qualidade e de apoio à conferência da transcrição.

O relatório não resume a reunião. Ele reúne, com marcação de tempo, os pontos que merecem
conferência humana (trechos incertos, inaudíveis, frases descartadas como alucinação) e um
índice extrativo (citações literais) de menções a valores, datas, prazos e encaminhamentos,
que são as informações que mais exigem exatidão.
"""

from __future__ import annotations

import re
from collections import defaultdict

from . import tempo
from .intervalos import unir
from .modelos import Marcador, Palavra
from .montagem import ROTULO_DESCONHECIDO
from .nomes import agrupar, sugerir
from .texto import juntar_palavras, termina_frase

_MESES = "janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro"
CATEGORIAS: dict[str, list[str]] = {
    "Valores monetários": [
        r"R\$\s?\d[\d.,]*(?:\s?(?:mil|milh(?:ão|ões)|bilh(?:ão|ões)))?",
        r"\b\d[\d.,]*\s?(?:mil\s+)?(?:reais|dólares|euros)\b",
        r"\b(?:mil|milh(?:ão|ões)|bilh(?:ão|ões)) de (?:reais|dólares|euros)\b",
    ],
    "Datas e prazos": [
        r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b",
        rf"\b\d{{1,2}} de (?:{_MESES})\b",
        rf"\b(?:{_MESES})\b",
        r"\bdia \d{1,2}\b",
        r"\b(?:segunda|terça|quarta|quinta|sexta)(?:-feira)?\b",
        r"\b(?:sábado|domingo)\b",
        r"\bprazos?\b",
        r"\bamanhã\b",
        r"\b(?:semana|mês|ano) que vem\b",
        r"\bpróxim[oa] (?:semana|mês|ano|reunião)\b",
        r"\baté (?:o )?(?:fim|final) d[oa]\b",
    ],
    "Horários": [r"\b\d{1,2}h\d{0,2}\b", r"\b\d{1,2}:\d{2}\b", r"\b\d{1,2} horas?\b"],
    "Percentuais": [r"\b\d+(?:[.,]\d+)?\s?%", r"\bpor cento\b"],
    "Decisões, tarefas e encaminhamentos": [
        r"\bdecid(?:imos|ido|ida|iu)\b",
        r"\bficou (?:decidido|combinado|definido|acordado)\b",
        r"\bcombinad[oa]\b",
        r"\baprovad[oa]s?\b|\baprovamos\b",
        r"\bencaminhamentos?\b",
        r"\bfica(?:r)? responsável\b|\bresponsáve(?:l|is) (?:por|pela|pelo)\b",
        r"\bpendente\b|\bpendências?\b",
        r"\bpróximos passos\b",
        r"\b(?:vou|vai|vamos|fica de) (?:fazer|mandar|enviar|levantar|verificar|preparar|organizar|agendar|marcar|revisar)\b",
    ],
}
_RX_CATEGORIAS = {c: [re.compile(p, re.IGNORECASE) for p in ps] for c, ps in CATEGORIAS.items()}


def _descrever_filtros(filtros: list[str]) -> str:
    nomes = {"afftdn": "redução de ruído", "dynaudnorm": "normalização dinâmica de volume"}
    descr = [nomes.get(f.split("=", 1)[0], f.split("=", 1)[0]) for f in filtros]
    return ", ".join(["filtro passa-altas", "normalização de volume"] + descr)


def frases_com_tempo(palavras: list[Palavra], pausa: float = 1.0,
                     reticencias: bool = True) -> list[tuple[float, float, str | None, str]]:
    """Frases (início, fim, falante bruto, texto) respeitando trocas de falante.

    Com reticencias=False, '...' de hesitação não encerra a frase (útil para citações completas).
    """
    frases = []
    atual: list[Palavra] = []
    for p in palavras:
        if atual and (p.falante != atual[-1].falante or p.inicio - atual[-1].fim >= pausa):
            frases.append(atual)
            atual = []
        atual.append(p)
        if termina_frase(p.texto, reticencias):
            frases.append(atual)
            atual = []
    if atual:
        frases.append(atual)
    return [(f[0].inicio, f[-1].fim, f[0].falante, juntar_palavras([p.texto for p in f])) for f in frases]


def _tabela(cabecalho: list[str], linhas: list[list[str]]) -> list[str]:
    def esc(s: str) -> str:
        return s.replace("|", "\\|").replace("\n", " ")

    out = ["| " + " | ".join(cabecalho) + " |", "|" + "|".join("---" for _ in cabecalho) + "|"]
    out += ["| " + " | ".join(esc(c) for c in l) + " |" for l in linhas]
    return out


def gerar(dados: dict, exibir: dict[str, str], palavras: list[Palavra], marcadores: list[Marcador]) -> str:
    nome = lambda f: exibir.get(f, ROTULO_DESCONHECIDO) if f else ROTULO_DESCONHECIDO  # noqa: E731
    arq = dados["arquivo"]
    proc = dados["processamento"]
    out = [f"# Relatório de qualidade: {arq['nome']}", ""]
    out += [
        "Este relatório apoia a conferência da transcrição. Ele não resume a reunião: todas as",
        "citações abaixo são trechos literais da transcrição, com a marcação de tempo para",
        "localizar o ponto exato na gravação.",
        "",
        "## Processamento",
        "",
        f"- **Arquivo:** {arq['nome']} ({tempo.duracao_legivel(arq['duracao'])})",
        f"- **Processado em:** {dados['gerado_em']}",
        f"- **Tempo total de processamento:** {tempo.duracao_legivel(proc.get('tempo_total_s', 0))}",
        f"- **Reconhecimento de fala:** {proc.get('descricao_asr', '')}",
        f"- **Dispositivo:** {proc.get('dispositivo', '')}",
        f"- **Diarização:** {proc.get('descricao_diarizacao', '')}",
    ]
    pre = proc.get("preprocessamento") or {}
    if pre:
        med = pre.get("medicoes", {})
        out += [
            f"- **Canais:** {pre.get('canais', {}).get('decisao', '')}",
            f"- **Nível de fala / ruído de fundo:** {med.get('nivel_fala_db')} dBFS / {med.get('nivel_ruido_db')} dBFS "
            f"(relação sinal-ruído estimada: {med.get('snr_db')} dB)",
            f"- **Tratamento do áudio para o reconhecimento:** {_descrever_filtros(pre.get('filtros_asr') or [])}",
        ]
        for o in pre.get("observacoes", []):
            out.append(f"- {o}")
    for o in dados.get("observacoes", []):
        out.append(f"- {o}")
    etapas = proc.get("tempos_etapas_s") or {}
    if etapas:
        out.append("- **Tempo por etapa:** " + ", ".join(f"{k} {tempo.duracao_legivel(v)}" for k, v in etapas.items()))

    # Participantes (tempo de fala inclui pausas curtas entre palavras do mesmo falante)
    out += ["", "## Participantes", ""]
    intervalos_por: dict[str, list] = defaultdict(list)
    palavras_por: dict[str, int] = defaultdict(int)
    primeira: dict[str, float] = {}
    for p in palavras:
        n = nome(p.falante)
        intervalos_por[n].append((p.inicio, p.fim))
        palavras_por[n] += 1
        primeira.setdefault(n, p.inicio)
    fala_por = {n: sum(b - a for a, b in unir(iv, tolerancia=1.0)) for n, iv in intervalos_por.items()}
    total = sum(fala_por.values()) or 1.0
    linhas = []
    for n in sorted(fala_por, key=lambda x: primeira[x]):
        linhas.append([n, tempo.hms(primeira[n]), tempo.duracao_legivel(fala_por[n]),
                       f"{100 * fala_por[n] / total:.0f}%", str(palavras_por[n])])
    out += _tabela(["Participante", "Primeira fala", "Tempo de fala (aprox.)", "Parcela", "Palavras"], linhas)

    # Qualidade
    rev = dados.get("revisao", {}).get("estatisticas", {})
    n_incertas = sum(1 for p in palavras if p.incerta)
    n_inaud = sum(1 for m in marcadores if m.tipo == "inaudivel")
    n_simul = sum(1 for m in marcadores if m.tipo == "simultanea")
    aluc = dados.get("alucinacoes_removidas", [])
    out += ["", "## Indicadores de qualidade", ""]
    out += [
        f"- Palavras transcritas: {len(palavras)}",
        f"- Palavras sinalizadas como incertas: {n_incertas} ({100 * n_incertas / max(1, len(palavras)):.1f}%)",
        f"- Trechos inaudíveis: {n_inaud}",
        f"- Falas simultâneas não transcritas: {n_simul}",
        f"- Trechos revisados no segundo passo (três decodificações por trecho): {rev.get('janelas', 0)} "
        f"({rev.get('alteradas', 0)} com texto alterado ou sinalizado)",
        f"- Palavras recuperadas de trechos omitidos no primeiro passo: {rev.get('palavras_recuperadas', 0)}",
        f"- Frases descartadas como alucinação do modelo: {len(aluc)}",
    ]

    # Pontos para conferência
    pontos: list[tuple[float, str, str, str]] = []
    grupo: list[Palavra] = []
    incertezas = dados.get("revisao", {}).get("incertezas", [])

    def alternativas(ini: float, fim: float) -> str:
        alts: list[str] = []
        for inc in incertezas:
            if inc["inicio"] < fim + 0.3 and inc["fim"] > ini - 0.3:
                alts += [a for a in inc["alternativas"] if a not in alts]
        return f" (outras hipóteses ouvidas: {'; '.join(alts)})" if alts else ""

    def fechar_grupo() -> None:
        if grupo:
            pontos.append((grupo[0].inicio, nome(grupo[0].falante), "trecho incerto",
                           juntar_palavras([g.texto for g in grupo]) + alternativas(grupo[0].inicio, grupo[-1].fim)))
            grupo.clear()

    for p in palavras:
        if not p.incerta:
            fechar_grupo()
            continue
        if grupo and p.falante != grupo[-1].falante:
            fechar_grupo()
        grupo.append(p)
    fechar_grupo()
    for m in marcadores:
        if m.tipo == "inaudivel":
            pontos.append((m.inicio, nome(m.falante), "inaudível", f"{m.fim - m.inicio:.1f} s sem transcrição"))
    for a in aluc:
        pontos.append((a["inicio"], "", "descartado", f"\"{a['texto']}\" ({a['motivo']})"))
    pontos.sort()
    out += ["", "## Pontos para conferência", ""]
    if pontos:
        out += ["Ouça a gravação nestes pontos para confirmar ou corrigir o texto.", ""]
        out += _tabela(["Tempo", "Participante", "Tipo", "Trecho"], [[tempo.hms(t), n, tp, tx] for t, n, tp, tx in pontos])
    else:
        out.append("Nenhum ponto de dúvida registrado.")

    frases = frases_com_tempo(palavras)

    # Sugestões de nomes
    out += ["", "## Sugestões de nomes (exigem confirmação)", ""]
    evid = sugerir(frases)
    if evid:
        out += ["Os nomes abaixo foram mencionados na própria fala. Nenhum foi aplicado automaticamente.",
                "Autoidentificação (\"aqui é a Ana\") é evidência forte; indício indireto vem de alguém",
                "se dirigir à pessoa pelo nome logo antes ou logo depois da fala dela. Para aplicar:", "",
                "```", f"transcritor nomear \"{arq['base']}.json\" --interativo", "```", ""]
        linhas = []
        for f, itens in sorted(agrupar(evid).items(), key=lambda x: nome(x[0])):
            for nome_sug, diretas, indiretas, exemplos in itens[:3]:
                partes = []
                if diretas:
                    partes.append(f"{diretas} autoidentificação" + ("ões" if diretas > 1 else ""))
                if indiretas:
                    partes.append(f"{indiretas} indício" + ("s" if indiretas > 1 else "") + " indireto"
                                  + ("s" if indiretas > 1 else ""))
                ex = exemplos[0]
                linhas.append([nome(f), nome_sug, ", ".join(partes), f"[{tempo.hms(ex.tempo)}] {ex.trecho}"])
        out += _tabela(["Participante", "Nome sugerido", "Evidências", "Exemplo"], linhas)
    else:
        out.append("Nenhuma autoidentificação ou menção clara de nomes foi encontrada.")
    frases = frases_com_tempo(palavras, reticencias=False)

    # Índice de menções
    out += ["", "## Índice de menções para conferência", "",
            "Citações literais que contêm valores, datas, prazos, horários, percentuais ou encaminhamentos.", ""]
    algum = False
    for cat, regexes in _RX_CATEGORIAS.items():
        achados = [(t, f, tx) for t, _fim, f, tx in frases if any(r.search(tx) for r in regexes)]
        if not achados:
            continue
        algum = True
        out += [f"### {cat}", ""]
        out += [f"- **[{tempo.hms(t)}] {nome(f)}:** {tx}" for t, f, tx in achados]
        out.append("")
    if not algum:
        out.append("Nenhuma menção encontrada.")
    return "\n".join(out).rstrip() + "\n"
