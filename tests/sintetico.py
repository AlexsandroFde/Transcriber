"""Transcrição sintética (formato transcritor/1) montada com as funções reais do processamento.

Usada nos testes da API e dos serviços, que não carregam modelos de IA.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from transcritor import __version__
from transcritor.processamento.modelos import Marcador, Palavra, Turno
from transcritor.processamento.montagem import OpcoesMontagem, atribuir_falantes, rotular, suavizar
from transcritor.processamento.revisao import OpcoesRevisao

FALAS = [
    (0.2, "S0", "Bom dia a todos. Aqui é a Mariana, da coordenação."),
    (4.2, "S1", "Obrigado, Mariana. O prazo é dia 15 de dezembro."),
    (7.2, "S0", "Certo. Roberto, você pode enviar o relatório?"),
    (12.2, "S2", "Posso sim, até sexta-feira."),
]


def dados_sinteticos(entrada: Path) -> dict:
    exclusivos = [Turno(0.0, 4.0, "S0"), Turno(4.0, 7.0, "S1"), Turno(7.0, 12.0, "S0"), Turno(12.0, 15.0, "S2")]
    palavras: list[Palavra] = []
    for t0, _falante, frase in FALAS:
        for i, w in enumerate(frase.split(" ")):
            palavras.append(Palavra(t0 + i * 0.3, t0 + i * 0.3 + 0.25, " " + w, 0.95))
    palavras[2].incerta = True  # "a" (de "Bom dia a todos")
    op = OpcoesMontagem()
    suavizar(palavras, atribuir_falantes(palavras, exclusivos, op, exclusivos), op, exclusivos)
    marcadores = [Marcador(10.0, 11.5, "inaudivel", "S0")]
    rotulos = rotular(palavras, marcadores, exclusivos)
    return {
        "formato": "transcritor/1",
        "versao_programa": __version__,
        "gerado_em": "05/11/2026 10:00",
        "arquivo": {"nome": entrada.name, "caminho": str(entrada), "base": entrada.stem, "duracao": 15.0,
                    "faixas_audio": [{"indice_audio": 0, "canais": 1, "taxa": 16000, "codec": "pcm_s16le",
                                      "idioma": None, "titulo": None}]},
        "processamento": {
            "descricao_asr": "Whisper large-v3 (faster-whisper), português, com revisão em segundo passo",
            "descricao_diarizacao": "teste", "modelo": "large-v3", "modelo_revisao": None,
            "dispositivo": "cpu (int8) | GPU: nenhuma (CPU)", "contexto": None, "glossario": [], "prompt": "",
            "hotwords": "",
            "preprocessamento": {"modo": "auto", "canais": {"decisao": "áudio mono"},
                                 "medicoes": {"nivel_fala_db": -24.0, "nivel_ruido_db": -60.0, "snr_db": 36.0,
                                              "dispersao_volume_db": 3.0, "fala_detectada_s": 12.0,
                                              "pico_fala_db": -20.0},
                                 "filtros_asr": [], "ganho_base_db": 2.0, "ganho_asr_db": None, "observacoes": []},
            "opcoes_revisao": asdict(OpcoesRevisao()), "opcoes_montagem": asdict(op),
            "tempos_etapas_s": {"extração": 0.1, "montagem": 0.1}, "tempo_total_s": 1.0,
        },
        "observacoes": [],
        "falantes": {f: {"rotulo": r, "nome": None} for f, r in rotulos.items()},
        "palavras": [p.para_dict() for p in palavras],
        "marcadores": [m.para_dict() for m in marcadores],
        "diarizacao": {"backend": "livre", "turnos": [t.para_dict() for t in exclusivos],
                       "exclusivos": [t.para_dict() for t in exclusivos], "observacoes": []},
        "revisao": {"estatisticas": {"janelas": 1, "alteradas": 1, "palavras_recuperadas": 0, "inaudiveis": 1,
                                     "palavras_incertas": 1},
                    "incertezas": [{"inicio": 0.8, "fim": 1.05, "escolhido": "a", "alternativas": ["(nenhuma palavra)"]}],
                    "registros": []},
        "alucinacoes_removidas": [{"inicio": 14.5, "fim": 14.9, "texto": "Obrigada.", "motivo": "teste"}],
    }
