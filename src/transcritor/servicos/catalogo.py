"""Catálogo das opções de transcrição: valores aceitos, rótulos e explicações.

A interface monta os campos a partir daqui, para que valores permitidos, padrões e textos
de ajuda tenham uma única fonte (o backend).
"""

from __future__ import annotations

from typing import get_args

from ..processamento.revisao import OpcoesRevisao
from .contratos import (
    CatalogoOpcoes,
    Diarizacao,
    Dispositivo,
    Estilo,
    Formato,
    LimiteNumerico,
    OpcaoCatalogo,
    OpcoesTranscricao,
    Precisao,
    PreProcessamento,
)

EXTENSOES_MIDIA = (".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm", ".m4v", ".mpg", ".mpeg", ".ts", ".mts", ".flv",
                   ".3gp", ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac", ".wma", ".amr", ".aif",
                   ".aiff")
EXTENSOES_VIDEO = (".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm", ".m4v", ".mpg", ".mpeg", ".ts", ".mts", ".flv",
                   ".3gp")

_MODELOS = [
    ("large-v3", "Whisper large-v3", "O mais preciso para português. Recomendado.", True),
    ("large-v3-turbo", "Whisper large-v3 turbo", "Bem mais rápido e um pouco menos preciso. Útil sem placa de vídeo.",
     False),
    ("large-v2", "Whisper large-v2", "Versão anterior. Pode servir como modelo da revisão, para uma segunda opinião.",
     False),
]
_DISPOSITIVOS = {
    "auto": ("Automático", "Usa a placa de vídeo NVIDIA quando disponível; senão, o processador.", True),
    "cuda": ("Placa de vídeo (CUDA)", "Exige placa NVIDIA compatível, com pelo menos 6 GB de memória.", False),
    "cpu": ("Processador", "Funciona em qualquer computador, mas cerca de 10 vezes mais lento.", False),
}
_PRECISOES = {
    "auto": ("Automática", "float16 na placa de vídeo e int8 no processador.", True),
    "float16": ("float16", "Padrão na placa de vídeo.", False),
    "int8_float16": ("int8_float16", "Usa menos memória da placa de vídeo. Escolha se faltar memória.", False),
    "int8": ("int8", "Padrão no processador, com menor uso de memória.", False),
    "float32": ("float32", "Precisão numérica máxima; mais lento e com mais memória.", False),
    "bfloat16": ("bfloat16", "Alternativa ao float16 em placas de vídeo recentes.", False),
}
_PRE = {
    "auto": ("Automático", "Só reduz ruído e equaliza o volume quando as medições do áudio indicam necessidade.", True),
    "leve": ("Leve", "Apenas filtro passa-altas e normalização do volume da fala.", False),
    "forte": ("Forte", "Sempre aplica redução de ruído e normalização dinâmica. Para gravações muito ruidosas.",
              False),
    "nenhum": ("Nenhum", "Usa o áudio como está, ajustando apenas o volume máximo.", False),
}
_DIARIZACAO = {
    "auto": ("Automática", "Usa o modelo community-1 quando há token do Hugging Face; sem token, o pipeline "
                           "pyannote 3.1 de acesso livre.", True),
    "pyannote": ("pyannote community-1", "O modelo mais recente. Exige token do Hugging Face com os termos aceitos.",
                 False),
    "livre": ("pyannote 3.1 (acesso livre)", "Componentes de acesso livre, sem token. Nos testes, atribuiu 95% a 97% "
                                             "das falas à pessoa certa.", False),
    "sherpa": ("sherpa-onnx", "Último recurso; erra mais quando há falas sobrepostas.", False),
    "nenhuma": ("Desativada", "Não separa os participantes: todo o texto aparece como \"Fala\".", False),
}
_ESTILOS = {
    "literal": ("Literal", "Preserva hesitações e repetições (\"é\", \"né\", \"a gente, a gente\").", True),
    "padrao": ("Padrão do modelo", "O modelo decide sobre hesitações: texto mais limpo e menos fiel à fala.", False),
}
_FORMATOS = {
    "docx": ("Word (.docx)", "Para ler, imprimir ou editar. Trechos incertos destacados em amarelo."),
    "md": ("Markdown (.md)", "Texto com formatação leve."),
    "txt": ("Texto (.txt)", "Texto simples."),
    "srt": ("Legendas SRT (.srt)", "Para abrir junto com o vídeo (VLC, YouTube etc.), com o nome de quem fala."),
    "vtt": ("Legendas WebVTT (.vtt)", "Legendas para players da web."),
    "json": ("Dados completos (.json)", "Sempre gerado: cada palavra com tempo e confiança. Usado para renomear "
                                        "participantes e gerar os arquivos de novo."),
}


def _opcoes(valores: tuple, descricoes: dict) -> list[OpcaoCatalogo]:
    return [OpcaoCatalogo(valor=v, rotulo=descricoes[v][0], descricao=descricoes[v][1],
                          recomendado=descricoes[v][2] if len(descricoes[v]) > 2 else False) for v in valores]


def catalogo() -> CatalogoOpcoes:
    padroes = OpcoesTranscricao().model_dump(mode="json", exclude={"hf_token"})
    return CatalogoOpcoes(
        padroes=padroes,
        modelos=[OpcaoCatalogo(valor=v, rotulo=r, descricao=d, recomendado=rec) for v, r, d, rec in _MODELOS],
        dispositivos=_opcoes(get_args(Dispositivo), _DISPOSITIVOS),
        precisoes=_opcoes(get_args(Precisao), _PRECISOES),
        pre_processamento=_opcoes(get_args(PreProcessamento), _PRE),
        diarizacao=_opcoes(get_args(Diarizacao), _DIARIZACAO),
        estilos=_opcoes(get_args(Estilo), _ESTILOS),
        formatos=_opcoes(("docx", "md", "txt", "srt", "vtt", "json"), _FORMATOS),
        extensoes_midia=list(EXTENSOES_MIDIA),
        limites={
            "participantes": LimiteNumerico(minimo=1, maximo=99, passo=1),
            "beam": LimiteNumerico(minimo=1, maximo=50, passo=1, padrao=padroes["beam"]),
            "limiar_incerteza": LimiteNumerico(minimo=0.05, maximo=0.99, passo=0.01,
                                               padrao=OpcoesRevisao().limiar_sem_maioria),
        },
    )


assert set(get_args(Formato)) == set(_FORMATOS)
