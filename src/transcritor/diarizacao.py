"""Diarização: identifica quem fala e quando.

Backends, em ordem de preferência no modo "auto":
  * pyannote: `pyannote/speaker-diarization-community-1`, o melhor modelo aberto disponível.
    Exige aceitar os termos do modelo no Hugging Face e um token de acesso.
  * livre: o pipeline do pyannote 3.1 montado só com componentes de acesso livre: o modelo
    de segmentação pyannote 3.0 (licença MIT) na cópia em ONNX distribuída pelo projeto
    sherpa-onnx, o embedding WeSpeaker ResNet34 (CC-BY-4.0, sem restrição no Hugging Face)
    e o agrupamento aglomerativo com os hiperparâmetros publicados do 3.1. Dispensa token e,
    nos testes, separou as vozes quase tão bem quanto o esperado do original.
  * sherpa: último recurso (agrupamento simples, sensível a falas sobrepostas).

Os dois primeiros fornecem a versão "exclusiva" (um falante por vez), ideal para atribuir
palavras, e detectam falas simultâneas. O áudio é passado já carregado em memória; nada é
enviado para fora da máquina.
"""

from __future__ import annotations

import contextlib
import gc
import logging
import os
import tarfile
import types
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .ambiente import carregar_torch, pasta_modelos
from .audio import TAXA
from .modelos import Turno

log = logging.getLogger("transcritor")

MODELO_PYANNOTE = "pyannote/speaker-diarization-community-1"
PAGINA_MODELO = f"https://huggingface.co/{MODELO_PYANNOTE}"

URL_SEGMENTACAO = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/"
                   "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2")
# TitaNet (NVIDIA NeMo): na calibração separou vozes parecidas melhor que o WeSpeaker ResNet34.
URL_EMBEDDING = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
                 "nemo_en_titanet_small.onnx")
# Limiar de agrupamento do sherpa. Valores maiores juntam mais vozes. 0,8 erra para o lado de
# separar demais, o que se corrige unindo rótulos com `transcritor nomear`; juntar duas
# pessoas num mesmo rótulo não tem correção posterior.
LIMIAR_SHERPA = 0.8

# Backend "livre": embedding sem restrição e hiperparâmetros do pyannote/speaker-diarization-3.1.
EMBEDDING_LIVRE = "pyannote/wespeaker-voxceleb-resnet34-LM"
PARAMETROS_LIVRE = {
    "segmentation": {"min_duration_off": 0.0},
    "clustering": {"method": "centroid", "min_cluster_size": 12, "threshold": 0.7045654963945799},
}


class ErroDiarizacao(RuntimeError):
    pass


@dataclass
class ResultadoDiarizacao:
    backend: str
    turnos: list[Turno]  # podem se sobrepor (falas simultâneas)
    exclusivos: list[Turno]  # um falante por vez
    observacoes: list[str] = field(default_factory=list)

    @property
    def falantes(self) -> list[str]:
        return sorted({t.falante for t in self.turnos})

    def para_dict(self) -> dict:
        return {
            "backend": self.backend,
            "turnos": [t.para_dict() for t in self.turnos],
            "exclusivos": [t.para_dict() for t in self.exclusivos],
            "observacoes": self.observacoes,
        }

    @classmethod
    def de_dict(cls, d: dict) -> "ResultadoDiarizacao":
        return cls(
            backend=d["backend"],
            turnos=[Turno.de_dict(t) for t in d["turnos"]],
            exclusivos=[Turno.de_dict(t) for t in d["exclusivos"]],
            observacoes=list(d.get("observacoes", [])),
        )


def exclusivizar(turnos: list[Turno]) -> list[Turno]:
    """Converte turnos com sobreposição em turnos exclusivos.

    Em trechos simultâneos, mantém o falante cujo turno contínuo é mais longo
    (quem detém a palavra), já que é ele que o reconhecedor costuma transcrever.
    """
    if not turnos:
        return []
    pontos = sorted({t.inicio for t in turnos} | {t.fim for t in turnos})
    ordenados = sorted(turnos, key=lambda t: t.inicio)
    saida: list[Turno] = []
    ativos: list[Turno] = []
    j = 0
    for a, b in zip(pontos[:-1], pontos[1:]):
        if b - a <= 1e-6:
            continue
        while j < len(ordenados) and ordenados[j].inicio <= a + 1e-9:
            ativos.append(ordenados[j])
            j += 1
        ativos = [t for t in ativos if t.fim > a + 1e-9]
        cobrindo = [t for t in ativos if t.inicio <= a + 1e-9 and t.fim >= b - 1e-9]
        if not cobrindo:
            continue
        escolhido = max(cobrindo, key=lambda t: (t.duracao, -t.inicio))
        if saida and saida[-1].falante == escolhido.falante and abs(saida[-1].fim - a) < 1e-6:
            saida[-1] = Turno(saida[-1].inicio, b, escolhido.falante)
        else:
            saida.append(Turno(a, b, escolhido.falante))
    return saida


def regioes_de_fala(turnos: list[Turno]) -> list[tuple[float, float]]:
    from .intervalos import unir

    return unir(((t.inicio, t.fim) for t in turnos))


# ---------------------------------------------------------------------------
# pyannote
# ---------------------------------------------------------------------------


class _Gancho:
    """Recebe o progresso das etapas do pyannote."""

    _PESOS = {"segmentation": (0.0, 0.25), "speaker_counting": (0.25, 0.3), "embeddings": (0.3, 0.95),
              "discrete_diarization": (0.95, 1.0)}

    def __init__(self, progresso: Callable[[float], None] | None):
        self.progresso = progresso

    def __call__(self, nome, artefato, file=None, total=None, completed=None):
        if not self.progresso:
            return
        ini, fim = self._PESOS.get(nome, (0.0, 1.0))
        if total and completed is not None:
            self.progresso(ini + (fim - ini) * min(1.0, completed / max(total, 1)))
        else:
            self.progresso(fim)


def _diarizar_pyannote(audio: np.ndarray, token: str | None, num: int | None, minimo: int | None,
                       maximo: int | None, usar_gpu: bool,
                       progresso: Callable[[float], None] | None) -> ResultadoDiarizacao:
    if not token:
        raise ErroDiarizacao(
            "O modelo de diarização pyannote exige um token do Hugging Face. "
            f"Aceite os termos em {PAGINA_MODELO} e configure o token "
            "(comando: transcritor configurar-token SEU_TOKEN)."
        )
    carregar_torch()
    from pyannote.audio import Pipeline

    try:
        pipeline = Pipeline.from_pretrained(MODELO_PYANNOTE, token=token)
    except Exception as e:  # erros de rede/permissão
        raise ErroDiarizacao(f"Não foi possível carregar {MODELO_PYANNOTE}: {e}") from e
    if pipeline is None:
        raise ErroDiarizacao(
            f"Acesso negado ao modelo {MODELO_PYANNOTE}. Verifique se o token é válido e se os termos "
            f"de uso foram aceitos em {PAGINA_MODELO} com a mesma conta."
        )
    return executar_pipeline_pyannote(pipeline, audio, num, minimo, maximo, usar_gpu, progresso)


def executar_pipeline_pyannote(pipeline, audio: np.ndarray, num: int | None, minimo: int | None,
                               maximo: int | None, usar_gpu: bool,
                               progresso: Callable[[float], None] | None) -> ResultadoDiarizacao:
    """Executa um pipeline pyannote já carregado sobre o áudio em memória."""
    torch = carregar_torch()
    dispositivo = torch.device("cuda" if usar_gpu and torch.cuda.is_available() else "cpu")
    pipeline.to(dispositivo)
    kwargs: dict = {}
    if num:
        kwargs["num_speakers"] = num
    else:
        if minimo:
            kwargs["min_speakers"] = minimo
        if maximo:
            kwargs["max_speakers"] = maximo
    forma = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32)).unsqueeze(0)
    try:
        saida = pipeline({"waveform": forma, "sample_rate": TAXA}, hook=_Gancho(progresso), **kwargs)
    finally:
        del forma
    anot = saida.speaker_diarization if hasattr(saida, "speaker_diarization") else saida
    excl = getattr(saida, "exclusive_speaker_diarization", None)
    turnos = [Turno(float(s.start), float(s.end), str(r)) for s, _, r in anot.itertracks(yield_label=True)]
    if excl is not None:
        exclusivos = [Turno(float(s.start), float(s.end), str(r)) for s, _, r in excl.itertracks(yield_label=True)]
    else:
        exclusivos = exclusivizar(turnos)
    del pipeline, saida
    gc.collect()
    if dispositivo.type == "cuda":
        torch.cuda.empty_cache()
    turnos.sort(key=lambda t: (t.inicio, t.fim))
    exclusivos.sort(key=lambda t: (t.inicio, t.fim))
    return ResultadoDiarizacao("pyannote", turnos, exclusivos)


# ---------------------------------------------------------------------------
# sherpa-onnx (sem token)
# ---------------------------------------------------------------------------


def _baixar(url: str, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    temp = destino.with_suffix(destino.suffix + ".parcial")
    log.info("  Baixando %s", url.rsplit("/", 1)[-1])
    with urllib.request.urlopen(url, timeout=120) as resp, open(temp, "wb") as f:
        while True:
            bloco = resp.read(1 << 20)
            if not bloco:
                break
            f.write(bloco)
    os.replace(temp, destino)


def modelos_sherpa() -> tuple[Path, Path]:
    pasta = pasta_modelos() / "sherpa"
    seg = pasta / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"
    emb = pasta / URL_EMBEDDING.rsplit("/", 1)[-1]
    if not seg.exists():
        pacote = pasta / "segmentacao.tar.bz2"
        _baixar(URL_SEGMENTACAO, pacote)
        with tarfile.open(pacote, "r:bz2") as tar:
            tar.extractall(pasta, filter="data")
        pacote.unlink(missing_ok=True)
    if not emb.exists():
        _baixar(URL_EMBEDDING, emb)
    if not seg.exists():
        raise ErroDiarizacao(f"Modelo de segmentação não encontrado após o download: {seg}")
    return seg, emb


def _diarizar_sherpa(audio: np.ndarray, num: int | None, minimo: int | None, maximo: int | None,
                     limiar: float, progresso: Callable[[float], None] | None) -> ResultadoDiarizacao:
    import sherpa_onnx as so

    seg, emb = modelos_sherpa()
    threads = max(1, min(8, (os.cpu_count() or 4) - 1))

    def configurar(n_clusters: int) -> "so.OfflineSpeakerDiarization":
        cfg = so.OfflineSpeakerDiarizationConfig(
            segmentation=so.OfflineSpeakerSegmentationModelConfig(
                pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(seg)),
                num_threads=threads,
            ),
            embedding=so.SpeakerEmbeddingExtractorConfig(model=str(emb), num_threads=threads),
            clustering=so.FastClusteringConfig(num_clusters=n_clusters, threshold=limiar),
            min_duration_on=0.3,
            min_duration_off=0.5,
        )
        if not cfg.validate():
            raise ErroDiarizacao("Configuração inválida do sherpa-onnx.")
        return so.OfflineSpeakerDiarization(cfg)

    def rodar(n_clusters: int):
        sd = configurar(n_clusters)

        def cb(feitos: int, total: int) -> int:
            if progresso and total:
                progresso(feitos / total)
            return 0

        return sd.process(np.ascontiguousarray(audio, dtype=np.float32), callback=cb).sort_by_start_time()

    obs: list[str] = []
    resultado = rodar(num if num else -1)
    n = len({r.speaker for r in resultado})
    if not num and ((minimo and n < minimo) or (maximo and n > maximo)):
        alvo = int(np.clip(n, minimo or n, maximo or n))
        obs.append(f"Agrupamento automático encontrou {n} falantes; refeito com {alvo} (limites informados).")
        resultado = rodar(alvo)
    turnos = [Turno(float(r.start), float(r.end), f"SPEAKER_{int(r.speaker):02d}") for r in resultado]
    turnos.sort(key=lambda t: (t.inicio, t.fim))
    return ResultadoDiarizacao("sherpa", turnos, exclusivizar(turnos), obs)


# ---------------------------------------------------------------------------
# livre: pipeline do pyannote 3.1 com componentes sem restrição de acesso
# ---------------------------------------------------------------------------


def _segmentacao_onnx(caminho: Path):
    """Modelo de segmentação pyannote 3.0 executado em ONNX, com a interface de um PyanNet.

    O PyanNet (sem pesos treinados) fornece ao pyannote a geometria do modelo (janela de 10 s,
    589 quadros, campo receptivo de 991 amostras, passo de 270, 3 falantes em powerset);
    o cálculo em si é feito pelo ONNX com os pesos originais.
    """
    torch = carregar_torch()
    import onnxruntime as ort
    from pyannote.audio.core.task import Problem, Resolution, Specifications
    from pyannote.audio.models.segmentation import PyanNet

    modelo = PyanNet(sincnet={"stride": 10})
    modelo.specifications = Specifications(
        problem=Problem.MONO_LABEL_CLASSIFICATION, resolution=Resolution.FRAME, duration=10.0,
        min_duration=10.0, warm_up=(0.0, 0.0), classes=["speaker#1", "speaker#2", "speaker#3"],
        powerset_max_classes=2, permutation_invariant=True)
    modelo.build()
    modelo.eval()
    opcoes = ort.SessionOptions()
    opcoes.intra_op_num_threads = max(1, min(8, (os.cpu_count() or 4) - 1))
    opcoes.log_severity_level = 3
    sessao = ort.InferenceSession(str(caminho), sess_options=opcoes, providers=["CPUExecutionProvider"])
    entrada = sessao.get_inputs()[0].name

    def forward(self, waveforms, weights=None):
        saida = sessao.run(None, {entrada: waveforms.detach().cpu().numpy().astype(np.float32)})[0]
        return torch.from_numpy(saida).to(waveforms.device)

    modelo.forward = types.MethodType(forward, modelo)
    if modelo.num_frames(160000) != 589:
        raise ErroDiarizacao("Geometria inesperada do modelo de segmentação.")
    return modelo


@contextlib.contextmanager
def _sem_plda():
    """O agrupamento aglomerativo não usa PLDA; evita que o pipeline tente baixá-lo."""
    import pyannote.audio.pipelines.speaker_diarization as modulo

    original = modulo.get_plda
    modulo.get_plda = lambda *a, **k: None
    try:
        yield
    finally:
        modulo.get_plda = original


def _diarizar_livre(audio: np.ndarray, num: int | None, minimo: int | None, maximo: int | None,
                    usar_gpu: bool, progresso: Callable[[float], None] | None) -> ResultadoDiarizacao:
    carregar_torch()
    from pyannote.audio.pipelines import SpeakerDiarization

    seg, _ = modelos_sherpa()
    try:
        with _sem_plda():
            pipeline = SpeakerDiarization(
                segmentation=_segmentacao_onnx(seg), embedding=EMBEDDING_LIVRE, embedding_exclude_overlap=True,
                clustering="AgglomerativeClustering", embedding_batch_size=32, segmentation_batch_size=32)
        pipeline.instantiate(PARAMETROS_LIVRE)
    except ErroDiarizacao:
        raise
    except Exception as e:
        raise ErroDiarizacao(f"Não foi possível montar a diarização livre: {e}") from e
    res = executar_pipeline_pyannote(pipeline, audio, num, minimo, maximo, usar_gpu, progresso)
    res.backend = "livre"
    return res


def modelos_livre() -> None:
    """Baixa antecipadamente os componentes do backend livre."""
    modelos_sherpa()
    carregar_torch()
    from pyannote.audio.pipelines.speaker_verification import PretrainedSpeakerEmbedding

    PretrainedSpeakerEmbedding(EMBEDDING_LIVRE)


# ---------------------------------------------------------------------------


def diarizar(
    audio: np.ndarray,
    backend: str = "auto",
    token: str | None = None,
    num_falantes: int | None = None,
    min_falantes: int | None = None,
    max_falantes: int | None = None,
    usar_gpu: bool = True,
    limiar_sherpa: float = LIMIAR_SHERPA,
    progresso: Callable[[float], None] | None = None,
) -> ResultadoDiarizacao:
    """Executa a diarização com o backend pedido.

    "auto": pyannote community-1 (com token) -> livre (sem token) -> sherpa (último recurso).
    """
    observacoes: list[str] = []
    if backend in ("auto", "pyannote"):
        try:
            return _diarizar_pyannote(audio, token, num_falantes, min_falantes, max_falantes, usar_gpu, progresso)
        except ErroDiarizacao as e:
            if backend == "pyannote":
                raise
            if token:  # sem token a ausência do community-1 é esperada; com token, vale avisar
                log.warning("  Aviso: %s", e)
            log.info("    Usando o pipeline pyannote 3.1 com componentes de acesso livre (sem token).")
            observacoes.append(f"Modelo community-1 indisponível ({e}); usado o pipeline pyannote 3.1 livre.")
    if backend in ("auto", "livre"):
        try:
            res = _diarizar_livre(audio, num_falantes, min_falantes, max_falantes, usar_gpu, progresso)
            res.observacoes = observacoes + res.observacoes
            return res
        except ErroDiarizacao as e:
            if backend == "livre":
                raise
            log.warning("  Aviso: %s", e)
            log.warning("  Usando a diarização de último recurso (sherpa-onnx), de qualidade inferior.")
            observacoes.append(f"Diarização livre indisponível ({e}); usado o sherpa-onnx.")
    if backend in ("auto", "sherpa"):
        res = _diarizar_sherpa(audio, num_falantes, min_falantes, max_falantes, limiar_sherpa, progresso)
        res.observacoes = observacoes + res.observacoes
        return res
    raise ValueError(f"Backend de diarização desconhecido: {backend}")
