"""O documento da transcrição: leitura do JSON, montagem dos parágrafos e gravação das saídas.

O JSON gerado pelo processamento (formato "transcritor/1") é a fonte de tudo o que vem
depois: renomear participantes, reexportar formatos, exibir a transcrição na interface e
montar o relatório de conferência. Nada aqui depende de modelos de IA.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import exportar, relatorio
from .modelos import Marcador, Palavra, Turno
from .montagem import OpcoesMontagem, montar_blocos, texto_bloco

FORMATO_JSON = "transcritor/1"


def carregar_transcricao(caminho: Path) -> dict:
    dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    if dados.get("formato") != FORMATO_JSON:
        raise ValueError(f"{caminho} não é um arquivo de transcrição deste programa.")
    return dados


def exibicao(dados: dict) -> dict[str, str]:
    """Nome exibido de cada falante: o nome atribuído ou, sem ele, o rótulo."""
    return {f: (info.get("nome") or info["rotulo"]) for f, info in dados["falantes"].items()}


def numero_rotulo(rotulo: str) -> int:
    """'Participante 3' -> 3 (0 quando o rótulo não termina em número)."""
    try:
        return int(rotulo.rsplit(" ", 1)[-1])
    except ValueError:
        return 0


def participantes_exibicao(dados: dict) -> list[tuple[str, str]]:
    """(rótulos, nome exibido) na ordem dos rótulos; rótulos com o mesmo nome aparecem juntos."""
    exibir = exibicao(dados)
    por_nome: dict[str, list[str]] = {}
    for f, info in sorted(dados["falantes"].items(), key=lambda x: numero_rotulo(x[1]["rotulo"])):
        por_nome.setdefault(exibir[f], []).append(info["rotulo"])
    return [(", ".join(rots), nome) if nome not in rots else (nome, nome) for nome, rots in por_nome.items()]


def montar_documento(dados: dict) -> exportar.Documento:
    """Palavras, marcadores e parágrafos prontos para exportar ou exibir."""
    palavras = [Palavra.de_dict(p) for p in dados["palavras"]]
    marcadores = [Marcador.de_dict(m) for m in dados["marcadores"]]
    turnos = [Turno.de_dict(t) for t in (dados.get("diarizacao") or {}).get("turnos", [])]
    exibir = exibicao(dados)
    opm = OpcoesMontagem(**dados["processamento"].get("opcoes_montagem", {}))
    blocos = montar_blocos(palavras, marcadores, turnos, exibir, opm)
    return exportar.Documento(
        titulo=dados["arquivo"]["nome"],
        arquivo=dados["arquivo"]["nome"],
        duracao=float(dados["arquivo"]["duracao"]),
        gerado_em=dados["gerado_em"],
        descricao_asr=dados["processamento"]["descricao_asr"],
        descricao_diarizacao=dados["processamento"]["descricao_diarizacao"],
        participantes=participantes_exibicao(dados),
        blocos=blocos,
        palavras=palavras,
        marcadores=marcadores,
        exibir=exibir,
        observacoes=list(dados.get("observacoes", [])),
    )


def analisar_relatorio(dados: dict, doc: exportar.Documento | None = None) -> relatorio.Relatorio:
    doc = doc or montar_documento(dados)
    return relatorio.analisar(dados, doc.exibir, doc.palavras, doc.marcadores)


def arquivo_relatorio(pasta: Path, base: str) -> Path:
    return pasta / f"{base}_relatorio.md"


def gerar_saidas(dados: dict, pasta: Path, formatos: list[str], json_saida: Path | None = None) -> list[Path]:
    """Monta os blocos a partir do JSON e grava os formatos pedidos e o relatório."""
    doc = montar_documento(dados)
    base = dados["arquivo"]["base"]
    dados["blocos"] = [{"inicio": round(b.inicio, 2), "fim": round(b.fim, 2), "falante": b.falante,
                        "texto": texto_bloco(b)} for b in doc.blocos]
    formatos = list(dict.fromkeys(formatos))
    if "json" not in formatos:
        formatos.append("json")  # o JSON é a fonte para renomear e reexportar
    arquivos = exportar.salvar(doc, pasta, base, formatos, dados_json=dados)
    rel = arquivo_relatorio(pasta, base)
    rel.write_text(relatorio.gerar(dados, doc.exibir, doc.palavras, doc.marcadores), encoding="utf-8")
    arquivos.append(rel)
    return arquivos
