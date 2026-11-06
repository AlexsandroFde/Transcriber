"""Acompanhamento do progresso de uma tarefa: etapas, percentual e tempo restante.

O percentual geral pondera cada etapa pela sua duração típica (medida nas reuniões de
teste). A estimativa de tempo restante usa só o trabalho realmente executado: etapas
reaproveitadas do cache terminam na hora e distorceriam a previsão.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass

from .contratos import EtapaTarefa, ProgressoTarefa


@dataclass(frozen=True)
class DefinicaoEtapa:
    chave: str
    titulo: str
    peso: float


ETAPAS_TRANSCRICAO = (
    DefinicaoEtapa("extracao", "Extração do áudio", 0.04),
    DefinicaoEtapa("preprocessamento", "Tratamento do áudio", 0.06),
    DefinicaoEtapa("diarizacao", "Identificação dos participantes", 0.22),
    DefinicaoEtapa("transcricao", "Transcrição da fala", 0.42),
    DefinicaoEtapa("revisao", "Revisão dos trechos duvidosos", 0.20),
    DefinicaoEtapa("montagem", "Montagem dos arquivos", 0.06),
)
ETAPAS_VERIFICACAO = (DefinicaoEtapa("verificacao", "Verificação do ambiente", 1.0),)
ETAPAS_DOWNLOAD = (
    DefinicaoEtapa("reconhecimento", "Modelo de reconhecimento de fala", 0.70),
    DefinicaoEtapa("diarizacao", "Modelos de identificação de participantes", 0.25),
    DefinicaoEtapa("pyannote", "Modelo pyannote community-1 (com token)", 0.05),
)
ETAPAS_POR_TIPO = {"transcricao": ETAPAS_TRANSCRICAO, "verificacao": ETAPAS_VERIFICACAO,
                   "download_modelos": ETAPAS_DOWNLOAD}

_FEITAS = ("concluida", "reaproveitada", "ignorada")


class Acompanhamento:
    def __init__(self, etapas: Sequence[DefinicaoEtapa], relogio=time.monotonic):
        self.definicoes = list(etapas)
        n = len(self.definicoes)
        self.estados = ["pendente"] * n
        self.detalhes: list[str | None] = [None] * n
        self.inicios: list[float | None] = [None] * n
        self.duracoes: list[float | None] = [None] * n
        self.atual: int | None = None
        self.fracao: float | None = None
        self.mensagem: str | None = None
        self._relogio = relogio
        self._t0: float | None = None
        self._t_fim: float | None = None

    # -- eventos -------------------------------------------------------------

    def iniciar(self) -> None:
        self._t0 = self._relogio()

    def etapa(self, numero: int, texto: str | None, situacao: str = "executando") -> None:
        if not self.definicoes:
            return
        i = max(0, min(numero - 1, len(self.definicoes) - 1))
        agora = self._relogio()
        if self.atual is not None and self.atual != i:
            self._fechar(self.atual, agora)
        for k in range(i):
            if self.estados[k] == "pendente":
                self.estados[k] = "reaproveitada"  # não anunciada: o resultado veio do cache
        self.detalhes[i] = texto
        if texto:
            self.mensagem = texto
        if situacao == "executando":
            if self.estados[i] != "em_andamento":
                self.inicios[i] = agora
            self.estados[i] = "em_andamento"
            self.atual = i
            self.fracao = None
        else:
            self.estados[i] = "reaproveitada" if situacao == "reaproveitada" else "ignorada"
            self.atual = None
            self.fracao = None

    def progresso(self, fracao: float) -> None:
        self.fracao = max(0.0, min(1.0, float(fracao)))

    def informar(self, texto: str) -> None:
        if texto and texto.strip():
            self.mensagem = texto.strip()

    def _fechar(self, i: int, agora: float, estado: str = "concluida") -> None:
        if self.estados[i] == "em_andamento":
            self.estados[i] = estado
            inicio = self.inicios[i]
            self.duracoes[i] = (agora - inicio) if inicio is not None else None
        if self.atual == i:
            self.atual = None
            self.fracao = None

    def encerrar(self, estado_tarefa: str) -> None:
        """Fecha a etapa atual conforme o desfecho da tarefa."""
        agora = self._relogio()
        self._t_fim = agora
        if self.atual is not None:
            destino = {"concluida": "concluida", "falhou": "falhou"}.get(estado_tarefa, "interrompida")
            self._fechar(self.atual, agora, destino)
        if estado_tarefa == "concluida":
            self.estados = [e if e != "pendente" else "ignorada" for e in self.estados]

    # -- leitura ------------------------------------------------------------

    def _peso(self, i: int) -> float:
        return self.definicoes[i].peso

    def percentual(self) -> float:
        total = sum(d.peso for d in self.definicoes) or 1.0
        feito = sum(self._peso(i) for i, e in enumerate(self.estados) if e in _FEITAS)
        if self.atual is not None and self.fracao is not None:
            feito += self._peso(self.atual) * self.fracao
        return round(100.0 * min(1.0, feito / total), 1)

    def decorrido(self) -> float | None:
        if self._t0 is None:
            return None
        return (self._t_fim or self._relogio()) - self._t0

    def restante(self) -> float | None:
        if self._t_fim is not None or self._t0 is None:
            return None
        if self.atual is not None and self.fracao is None:
            return None  # etapa sem medida (carregando modelo etc.)
        agora = self._relogio()
        peso_exec = 0.0
        tempo_exec = 0.0
        for i, e in enumerate(self.estados):
            if e == "concluida" and self.duracoes[i] is not None:
                peso_exec += self._peso(i)
                tempo_exec += self.duracoes[i] or 0.0
        if self.atual is not None:
            peso_exec += self._peso(self.atual) * (self.fracao or 0.0)
            inicio = self.inicios[self.atual]
            tempo_exec += agora - (agora if inicio is None else inicio)
        if peso_exec < 0.03 or tempo_exec < 8.0:
            return None
        restante = sum(self._peso(i) for i, e in enumerate(self.estados) if e == "pendente")
        if self.atual is not None:
            restante += self._peso(self.atual) * (1.0 - (self.fracao or 0.0))
        return round(restante / (peso_exec / tempo_exec), 0)

    def instantaneo(self) -> ProgressoTarefa:
        agora = self._relogio()
        etapas = []
        for i, d in enumerate(self.definicoes):
            dur = self.duracoes[i]
            if self.estados[i] == "em_andamento" and self.inicios[i] is not None:
                dur = agora - self.inicios[i]
            etapas.append(EtapaTarefa(numero=i + 1, chave=d.chave, titulo=d.titulo, estado=self.estados[i],
                                      detalhe=self.detalhes[i], duracao_s=None if dur is None else round(dur, 1)))
        decorrido = self.decorrido()
        return ProgressoTarefa(
            percentual=self.percentual(),
            etapa_atual=None if self.atual is None else self.atual + 1,
            total_etapas=len(self.definicoes),
            fracao_etapa=None if self.fracao is None else round(self.fracao, 4),
            mensagem=self.mensagem,
            decorrido_s=None if decorrido is None else round(decorrido, 1),
            restante_estimado_s=self.restante(),
            etapas=etapas,
        )


def progresso_inicial(tipo: str) -> ProgressoTarefa:
    return Acompanhamento(ETAPAS_POR_TIPO.get(tipo, ())).instantaneo()
