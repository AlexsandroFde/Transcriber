"""Estruturas de dados compartilhadas pelo pipeline.

Todas as marcas de tempo estão em segundos, relativas ao início da gravação original.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Palavra:
    """Uma palavra reconhecida, com tempo, confiança e falante atribuído."""

    inicio: float
    fim: float
    texto: str  # como produzido pelo modelo (com espaço inicial e pontuação colada)
    prob: float
    falante: str | None = None
    incerta: bool = False
    origem: str = "passo1"  # passo1 | revisao | recuperada

    @property
    def meio(self) -> float:
        return (self.inicio + self.fim) / 2.0

    def para_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["inicio"] = round(self.inicio, 3)
        d["fim"] = round(self.fim, 3)
        d["prob"] = round(self.prob, 4)
        return d

    @classmethod
    def de_dict(cls, d: dict[str, Any]) -> "Palavra":
        return cls(
            inicio=float(d["inicio"]),
            fim=float(d["fim"]),
            texto=str(d["texto"]),
            prob=float(d.get("prob", 1.0)),
            falante=d.get("falante"),
            incerta=bool(d.get("incerta", False)),
            origem=str(d.get("origem", "passo1")),
        )


@dataclass
class Marcador:
    """Evento que não é palavra: trecho inaudível ou fala simultânea não transcrita."""

    inicio: float
    fim: float
    tipo: str  # "inaudivel" | "simultanea"
    falante: str | None = None
    detalhe: str = ""

    @property
    def meio(self) -> float:
        return (self.inicio + self.fim) / 2.0

    def para_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["inicio"] = round(self.inicio, 3)
        d["fim"] = round(self.fim, 3)
        return d

    @classmethod
    def de_dict(cls, d: dict[str, Any]) -> "Marcador":
        return cls(
            inicio=float(d["inicio"]),
            fim=float(d["fim"]),
            tipo=str(d["tipo"]),
            falante=d.get("falante"),
            detalhe=str(d.get("detalhe", "")),
        )


@dataclass
class Turno:
    """Intervalo em que um falante está ativo, segundo a diarização."""

    inicio: float
    fim: float
    falante: str

    @property
    def duracao(self) -> float:
        return self.fim - self.inicio

    def para_dict(self) -> dict[str, Any]:
        return {"inicio": round(self.inicio, 3), "fim": round(self.fim, 3), "falante": self.falante}

    @classmethod
    def de_dict(cls, d: dict[str, Any]) -> "Turno":
        return cls(float(d["inicio"]), float(d["fim"]), str(d["falante"]))


@dataclass
class SegmentoASR:
    """Segmento devolvido pelo reconhecedor, já mapeado para o tempo original."""

    inicio: float
    fim: float
    texto: str
    avg_logprob: float
    compression_ratio: float
    no_speech_prob: float
    temperatura: float
    palavras: list[Palavra] = field(default_factory=list)

    def para_dict(self) -> dict[str, Any]:
        return {
            "inicio": round(self.inicio, 3),
            "fim": round(self.fim, 3),
            "texto": self.texto,
            "avg_logprob": round(self.avg_logprob, 4),
            "compression_ratio": round(self.compression_ratio, 4),
            "no_speech_prob": round(self.no_speech_prob, 4),
            "temperatura": self.temperatura,
            "palavras": [p.para_dict() for p in self.palavras],
        }

    @classmethod
    def de_dict(cls, d: dict[str, Any]) -> "SegmentoASR":
        return cls(
            inicio=float(d["inicio"]),
            fim=float(d["fim"]),
            texto=str(d["texto"]),
            avg_logprob=float(d["avg_logprob"]),
            compression_ratio=float(d["compression_ratio"]),
            no_speech_prob=float(d["no_speech_prob"]),
            temperatura=float(d["temperatura"]),
            palavras=[Palavra.de_dict(p) for p in d.get("palavras", [])],
        )


@dataclass
class Trecho:
    """Pedaço de texto renderizado dentro de um bloco."""

    tipo: str  # "texto" | "incerto" | "marcador"
    texto: str


@dataclass
class Bloco:
    """Parágrafo da transcrição final: um falante, um timestamp, vários trechos."""

    inicio: float
    fim: float
    falante: str | None
    trechos: list[Trecho] = field(default_factory=list)
    sobreposto_a: list[str] = field(default_factory=list)
