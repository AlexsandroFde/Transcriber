"""Exportação da transcrição: Markdown, TXT, DOCX, SRT, VTT e JSON."""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

from . import tempo
from .modelos import Bloco, Marcador, Palavra
from .montagem import ROTULO_DESCONHECIDO, _texto_marcador, texto_bloco
from .texto import juntar_palavras, termina_frase

FORMATOS = ("md", "txt", "docx", "srt", "vtt", "json")

LEGENDA = [
    ("[inaudível]", "fala detectada, mas não compreensível no áudio."),
    ("[trecho incerto: ...]", "melhor hipótese do sistema, sem confirmação; conferir na gravação."),
    ("[falas simultâneas com ...]", "a fala começa enquanto outra pessoa ainda está falando."),
    ("[falas simultâneas: ...]", "outra pessoa falou ao mesmo tempo, sem que fosse possível transcrever."),
]


@dataclass
class Documento:
    titulo: str
    arquivo: str
    duracao: float
    gerado_em: str
    descricao_asr: str
    descricao_diarizacao: str
    participantes: list[tuple[str, str]]  # (rótulo, nome exibido)
    blocos: list[Bloco]
    palavras: list[Palavra]
    marcadores: list[Marcador]
    exibir: dict[str, str]
    observacoes: list[str] = field(default_factory=list)


def _linhas_participantes(doc: Documento) -> list[str]:
    linhas = []
    for rotulo, exibido in doc.participantes:
        linhas.append(f"{exibido} ({rotulo})" if exibido != rotulo else rotulo)
    return linhas


# ---------------------------------------------------------------------------
# Markdown e TXT
# ---------------------------------------------------------------------------


def para_markdown(doc: Documento) -> str:
    out = [f"# Transcrição: {doc.titulo}", ""]
    out += [
        f"- **Arquivo:** {doc.arquivo}",
        f"- **Duração:** {tempo.duracao_legivel(doc.duracao)}",
        f"- **Processado em:** {doc.gerado_em}",
        f"- **Reconhecimento de fala:** {doc.descricao_asr}",
        f"- **Identificação de participantes:** {doc.descricao_diarizacao}",
        "",
        "## Participantes",
        "",
    ]
    out += [f"- {l}" for l in _linhas_participantes(doc)] or ["- (nenhum identificado)"]
    out += ["", "## Legenda", ""]
    out += [f"- `{m}`: {d}" for m, d in LEGENDA]
    if doc.observacoes:
        out += ["", "## Observações", ""]
        out += [f"- {o}" for o in doc.observacoes]
    out += ["", "---", "", "## Transcrição", ""]
    for b in doc.blocos:
        out.append(f"**[{tempo.hms(b.inicio)}] {b.falante}:** {texto_bloco(b)}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def para_txt(doc: Documento) -> str:
    out = [f"TRANSCRIÇÃO: {doc.titulo}", ""]
    out += [
        f"Arquivo: {doc.arquivo}",
        f"Duração: {tempo.duracao_legivel(doc.duracao)}",
        f"Processado em: {doc.gerado_em}",
        f"Reconhecimento de fala: {doc.descricao_asr}",
        f"Identificação de participantes: {doc.descricao_diarizacao}",
        "",
        "PARTICIPANTES",
    ]
    out += [f"  {l}" for l in _linhas_participantes(doc)] or ["  (nenhum identificado)"]
    out += ["", "LEGENDA"]
    out += [f"  {m}: {d}" for m, d in LEGENDA]
    if doc.observacoes:
        out += ["", "OBSERVAÇÕES"]
        out += [f"  {o}" for o in doc.observacoes]
    out += ["", "=" * 70, ""]
    for b in doc.blocos:
        out.append(f"[{tempo.hms(b.inicio)}] {b.falante}: {texto_bloco(b)}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


def _campo_pagina(paragrafo) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run = paragrafo.add_run()
    for tipo, texto in (("begin", None), (None, "PAGE"), ("end", None)):
        if tipo:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), tipo)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = texto
        run._r.append(el)


def salvar_docx(doc: Documento, caminho: Path) -> None:
    from docx import Document
    from docx.enum.text import WD_COLOR_INDEX, WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor, Cm

    d = Document()
    for secao in d.sections:
        secao.top_margin = secao.bottom_margin = Cm(2.0)
        secao.left_margin = secao.right_margin = Cm(2.2)
    normal = d.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    rpr = normal.element.get_or_add_rPr()
    lang = OxmlElement("w:lang")
    lang.set(qn("w:val"), "pt-BR")
    rpr.append(lang)
    normal.paragraph_format.space_after = Pt(6)

    d.core_properties.title = f"Transcrição: {doc.titulo}"
    d.core_properties.language = "pt-BR"
    d.add_heading(f"Transcrição: {doc.titulo}", level=0)

    tabela = d.add_table(rows=0, cols=2)
    tabela.style = "Light List Accent 1"
    for chave, valor in (
        ("Arquivo", doc.arquivo),
        ("Duração", tempo.duracao_legivel(doc.duracao)),
        ("Processado em", doc.gerado_em),
        ("Reconhecimento de fala", doc.descricao_asr),
        ("Identificação de participantes", doc.descricao_diarizacao),
    ):
        linha = tabela.add_row().cells
        linha[0].text = chave
        linha[1].text = valor
        for r in linha[0].paragraphs[0].runs:
            r.bold = True

    d.add_heading("Participantes", level=1)
    for l in _linhas_participantes(doc) or ["(nenhum identificado)"]:
        d.add_paragraph(l, style="List Bullet")

    d.add_heading("Legenda", level=1)
    for marca, descr in LEGENDA:
        p = d.add_paragraph(style="List Bullet")
        r = p.add_run(marca)
        r.italic = True
        if "incerto" in marca:
            r.font.highlight_color = WD_COLOR_INDEX.YELLOW
        else:
            r.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
        p.add_run(f": {descr}")

    if doc.observacoes:
        d.add_heading("Observações", level=1)
        for o in doc.observacoes:
            d.add_paragraph(o, style="List Bullet")

    d.add_heading("Transcrição", level=1)
    cinza = RGBColor(0x66, 0x66, 0x66)
    for b in doc.blocos:
        p = d.add_paragraph()
        cab = p.add_run(f"[{tempo.hms(b.inicio)}] {b.falante}: ")
        cab.bold = True
        if b.sobreposto_a:
            r = p.add_run(f"[falas simultâneas com {', '.join(b.sobreposto_a)}] ")
            r.italic = True
            r.font.color.rgb = cinza
        for i, t in enumerate(b.trechos):
            sep = "" if i == len(b.trechos) - 1 else " "
            if t.tipo == "texto":
                p.add_run(t.texto + sep)
            elif t.tipo == "incerto":
                interno = t.texto.rstrip(".,;:!?…")
                sufixo = t.texto[len(interno):]
                r = p.add_run(f"[trecho incerto: {interno}]")
                r.italic = True
                r.font.highlight_color = WD_COLOR_INDEX.YELLOW
                p.add_run(sufixo + sep)
            else:
                r = p.add_run(t.texto + sep)
                r.italic = True
                r.font.color.rgb = cinza

    rodape = d.sections[0].footer.paragraphs[0]
    rodape.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rodape.add_run(f"{doc.titulo}  |  página ")
    _campo_pagina(rodape)
    d.save(str(caminho))


# ---------------------------------------------------------------------------
# Legendas (SRT/VTT)
# ---------------------------------------------------------------------------


@dataclass
class Legenda:
    inicio: float
    fim: float
    falante: str
    texto: str


def _texto_elementos(elementos: list, exibir: dict[str, str]) -> str:
    partes: list[str] = []
    grupo: list[Palavra] = []
    incerto = False

    def fechar():
        nonlocal grupo
        if grupo:
            t = juntar_palavras([p.texto for p in grupo])
            if incerto:
                interno = t.rstrip(".,;:!?…")
                t = f"[trecho incerto: {interno}]{t[len(interno):]}"
            partes.append(t)
            grupo = []

    for e in elementos:
        if isinstance(e, Marcador):
            fechar()
            partes.append(_texto_marcador(e, exibir))
            continue
        if grupo and e.incerta != incerto:
            fechar()
        incerto = e.incerta
        grupo.append(e)
    fechar()
    return " ".join(partes)


def gerar_legendas(doc: Documento, max_dur: float = 6.0, max_chars: int = 80, pausa: float = 1.0) -> list[Legenda]:
    elementos = sorted([*doc.palavras, *doc.marcadores], key=lambda e: e.inicio)

    def nome(f):
        return doc.exibir.get(f, ROTULO_DESCONHECIDO) if f else ROTULO_DESCONHECIDO

    legendas: list[Legenda] = []
    atual: list = []
    falante_atual = None

    def fechar():
        nonlocal atual
        if atual:
            texto = _texto_elementos(atual, doc.exibir)
            if texto.strip():
                legendas.append(Legenda(atual[0].inicio, max(e.fim for e in atual), falante_atual or ROTULO_DESCONHECIDO, texto))
            atual = []

    for e in elementos:
        anexar = isinstance(e, Marcador) and e.tipo == "simultanea"
        f = falante_atual if (anexar and atual) else nome(e.falante)
        if atual:
            texto_prov = _texto_elementos(atual + [e], doc.exibir)
            ultimo = atual[-1]
            quebra_frase = (not isinstance(ultimo, Marcador)) and termina_frase(ultimo.texto) and (ultimo.fim - atual[0].inicio) >= 1.5
            if (f != falante_atual or e.fim - atual[0].inicio > max_dur or len(texto_prov) > max_chars
                    or e.inicio - ultimo.fim >= pausa or quebra_frase):
                fechar()
        if not atual:
            falante_atual = f
        atual.append(e)
    fechar()
    # Ajustes de tempo: duração mínima e sem sobreposição entre legendas consecutivas.
    for i, l in enumerate(legendas):
        proximo = legendas[i + 1].inicio if i + 1 < len(legendas) else None
        fim = max(l.fim + 0.2, l.inicio + 0.8)
        if proximo is not None:
            fim = min(fim, max(proximo - 0.01, l.fim))
        l.fim = max(fim, l.inicio + 0.1)
    return legendas


def _quebrar(texto: str, largura: int = 42) -> str:
    return "\n".join(textwrap.wrap(texto, width=largura, break_long_words=False)) or texto


def para_srt(doc: Documento) -> str:
    out = []
    for i, l in enumerate(gerar_legendas(doc), start=1):
        out.append(str(i))
        out.append(f"{tempo.srt(l.inicio)} --> {tempo.srt(l.fim)}")
        out.append(_quebrar(f"{l.falante}: {l.texto}"))
        out.append("")
    return "\n".join(out)


def para_vtt(doc: Documento) -> str:
    out = ["WEBVTT", ""]
    for l in gerar_legendas(doc):
        out.append(f"{tempo.vtt(l.inicio)} --> {tempo.vtt(l.fim)}")
        out.append(f"<v {l.falante}>{_quebrar(l.texto)}")
        out.append("")
    return "\n".join(out)


def salvar(doc: Documento, pasta: Path, base: str, formatos: list[str], dados_json: dict | None = None) -> list[Path]:
    """Grava os formatos pedidos. Retorna a lista de arquivos gerados."""
    pasta.mkdir(parents=True, exist_ok=True)
    gerados: list[Path] = []
    for fmt in formatos:
        destino = pasta / f"{base}.{fmt}"
        if fmt == "md":
            destino.write_text(para_markdown(doc), encoding="utf-8")
        elif fmt == "txt":
            destino.write_text(para_txt(doc), encoding="utf-8-sig")
        elif fmt == "docx":
            salvar_docx(doc, destino)
        elif fmt == "srt":
            destino.write_text(para_srt(doc), encoding="utf-8")
        elif fmt == "vtt":
            destino.write_text(para_vtt(doc), encoding="utf-8")
        elif fmt == "json":
            if dados_json is None:
                continue
            destino.write_text(json.dumps(dados_json, ensure_ascii=False, indent=1), encoding="utf-8")
        else:
            raise ValueError(f"Formato desconhecido: {fmt}")
        gerados.append(destino)
    return gerados
