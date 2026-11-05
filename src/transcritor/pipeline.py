"""Orquestração do processamento completo.

Cada etapa grava seu resultado em `<saída>/.trabalho/`, com uma chave calculada a partir do
arquivo de entrada e das opções relevantes. Ao rodar de novo (por exemplo, após uma queda de
energia no meio de uma gravação longa, ou mudando só o formato de saída), as etapas já
concluídas são reaproveitadas.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from . import __version__
from .ambiente import caminho_ffmpeg, configurar_log, descrever_gpu, token_hf
from .intervalos import unir
from .modelos import Marcador, Palavra, SegmentoASR, Turno
from .montagem import (OpcoesMontagem, atribuir_falantes, falante_em, marcadores_simultaneos,
                       montar_blocos, rotular, suavizar, texto_bloco)
from .qualidade import diagnosticar_segmento, termos_da_reuniao
from .revisao import OpcoesRevisao, lacunas
from . import exportar, relatorio, tempo

log = logging.getLogger("transcritor")

VERSAO_CACHE = "1"
VERSAO_REVISAO = "5"  # mude quando o algoritmo de revisão mudar, para invalidar o cache dessa etapa
SEM_DIARIZACAO = "SEM_DIARIZACAO"


@dataclass
class Opcoes:
    saida: Path | None = None
    modelo: str = "large-v3"
    modelo_revisao: str | None = None
    dispositivo: str = "auto"
    precisao: str = "auto"
    num_participantes: int | None = None
    min_participantes: int | None = None
    max_participantes: int | None = None
    contexto: str | None = None
    glossario: list[str] = field(default_factory=list)
    preprocessamento: str = "auto"
    faixa: str = "0"
    diarizacao: str = "auto"
    hf_token: str | None = None
    revisao: bool = True
    literal: bool = True
    formatos: list[str] = field(default_factory=lambda: list(exportar.FORMATOS))
    refazer: bool = False
    manter_audio: bool = False
    beam: int = 5
    limiar_sherpa: float = 0.8
    detalhado: bool = False
    opcoes_revisao: OpcoesRevisao = field(default_factory=OpcoesRevisao)
    opcoes_montagem: OpcoesMontagem = field(default_factory=OpcoesMontagem)


class Cache:
    def __init__(self, pasta: Path, ignorar: bool = False):
        self.pasta = pasta
        self.ignorar = ignorar

    @staticmethod
    def chave(*partes) -> str:
        bruto = json.dumps([VERSAO_CACHE, *partes], sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha1(bruto.encode("utf-8")).hexdigest()[:16]

    def ler(self, nome: str, chave: str) -> dict | None:
        if self.ignorar:
            return None
        arq = self.pasta / f"{nome}.json"
        if not arq.exists():
            return None
        try:
            dados = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return dados if dados.get("_chave") == chave else None

    def gravar(self, nome: str, chave: str, dados: dict) -> None:
        dados = dict(dados)
        dados["_chave"] = chave
        temp = self.pasta / f"{nome}.json.tmp"
        temp.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.pasta / f"{nome}.json")


class Progresso:
    """Barra de progresso simples com estimativa de tempo restante."""

    def __init__(self, rotulo: str):
        self.rotulo = rotulo
        self.t0 = time.time()
        self.tty = sys.stdout.isatty()
        self.ultimo = -1
        self.ultima_escrita = 0.0

    def __call__(self, fracao: float) -> None:
        pct = int(max(0.0, min(1.0, fracao)) * 100)
        agora = time.time()
        if self.tty:
            if pct == self.ultimo and agora - self.ultima_escrita < 1.0:
                return
            decorrido = agora - self.t0
            resta = ""
            if 3 <= pct < 100 and decorrido > 5:
                resta = f" | restam ~{tempo.duracao_legivel(decorrido * (100 - pct) / pct)}"
            barra = "#" * (pct // 4) + "-" * (25 - pct // 4)
            sys.stdout.write(f"\r    {self.rotulo} [{barra}] {pct:3d}%{resta}      ")
            sys.stdout.flush()
        else:
            # Sem terminal interativo (log redirecionado): uma linha a cada 10%.
            if self.ultimo < 0 or pct // 10 > self.ultimo // 10:
                print(f"    {self.rotulo}: {pct}%", flush=True)
        self.ultimo = pct
        self.ultima_escrita = agora

    def fim(self) -> None:
        if self.tty and self.ultimo >= 0:
            sys.stdout.write("\n")
            sys.stdout.flush()


def _etapa(n: int, total: int, texto: str) -> None:
    log.info("[%d/%d] %s", n, total, texto)


def processar(entrada: Path, op: Opcoes) -> Path:
    """Processa um arquivo de vídeo/áudio e grava todas as saídas. Retorna o caminho do JSON."""
    from .audio import carregar_wav, extrair_audio, preprocessar, sondar
    from .diarizacao import ResultadoDiarizacao, diarizar, regioes_de_fala

    t_inicio = time.time()
    entrada = entrada.resolve()
    if not entrada.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {entrada}")
    base = entrada.stem
    pasta = (op.saida.resolve() / base) if op.saida else entrada.parent / f"{base}_transcricao"
    trabalho = pasta / ".trabalho"
    trabalho.mkdir(parents=True, exist_ok=True)
    configurar_log(pasta / f"{base}.log", detalhado=op.detalhado)
    cache = Cache(trabalho, ignorar=op.refazer)
    tempos: dict[str, float] = {}
    total_etapas = 6
    ffmpeg = caminho_ffmpeg()

    log.info("")
    log.info("Arquivo: %s", entrada.name)
    log.info("Saída:   %s", pasta)
    info = sondar(entrada)
    if not info.faixas_audio:
        raise RuntimeError("O arquivo não possui faixa de áudio.")
    log.info("Duração: %s | faixas de áudio: %d", tempo.duracao_legivel(info.duracao or 0), len(info.faixas_audio))
    if len(info.faixas_audio) > 1 and op.faixa != "todas":
        log.info("  Observação: há %d faixas de áudio; usando a faixa %s (use --faixa-audio todas para mixar).",
                 len(info.faixas_audio), op.faixa)
    st = entrada.stat()
    id_entrada = {"caminho": str(entrada), "tamanho": st.st_size, "mtime": int(st.st_mtime), "faixa": op.faixa}

    extraido = trabalho / "audio_extraido.wav"
    base_wav = trabalho / "audio_base.wav"
    asr_wav = trabalho / "audio_asr.wav"

    # 1. Extração ---------------------------------------------------------------
    k_ext = Cache.chave("extracao", id_entrada)

    def garantir_extracao() -> dict:
        dados = cache.ler("extracao", k_ext)
        if dados is not None and extraido.exists():
            return dados
        t = time.time()
        _etapa(1, total_etapas, "Extraindo o áudio do arquivo")
        prog = Progresso("extração")
        dados = extrair_audio(ffmpeg, entrada, extraido, info, op.faixa, prog)
        prog.fim()
        cache.gravar("extracao", k_ext, dados)
        tempos["extração"] = time.time() - t
        return dados

    # 2. Pré-processamento ------------------------------------------------------
    k_pre = Cache.chave("pre", k_ext, op.preprocessamento)
    pre = cache.ler("preprocessamento", k_pre)
    if pre is None or not base_wav.exists() or not asr_wav.exists():
        garantir_extracao()
        t = time.time()
        _etapa(2, total_etapas, "Analisando e tratando o áudio (canais, volume, ruído)")
        res, fala_vad = preprocessar(ffmpeg, extraido, base_wav, asr_wav, op.preprocessamento)
        pre = {"resultado": res.para_dict(), "fala_vad": fala_vad}
        cache.gravar("preprocessamento", k_pre, pre)
        tempos["pré-processamento"] = time.time() - t
        log.info("    Canais: %s", res.canais.get("decisao"))
        m = res.medicoes
        log.info("    Fala detectada: %s | SNR estimada: %s dB", tempo.duracao_legivel(m["fala_detectada_s"]), m["snr_db"])
        for o in res.observacoes:
            log.info("    %s", o)
    else:
        _etapa(2, total_etapas, "Áudio já preparado (reaproveitado)")
    fala_vad = [tuple(x) for x in pre["fala_vad"]]
    if not op.manter_audio and extraido.exists():
        extraido.unlink()

    # 3. Diarização -------------------------------------------------------------
    dia: ResultadoDiarizacao | None = None
    token = token_hf(op.hf_token)
    if op.diarizacao != "nenhuma":
        from .diarizacao import EMBEDDING_LIVRE, MODELO_PYANNOTE, PARAMETROS_LIVRE, URL_EMBEDDING

        k_dia = Cache.chave("dia", k_pre, op.diarizacao, op.num_participantes, op.min_participantes,
                            op.max_participantes, op.limiar_sherpa, bool(token), MODELO_PYANNOTE, URL_EMBEDDING,
                            EMBEDDING_LIVRE, PARAMETROS_LIVRE)
        cache_dia = cache.ler("diarizacao", k_dia)
        if cache_dia is not None:
            dia = ResultadoDiarizacao.de_dict(cache_dia)
            _etapa(3, total_etapas, f"Participantes já identificados (reaproveitado, {dia.backend})")
        else:
            t = time.time()
            _etapa(3, total_etapas, "Identificando os participantes (diarização)")
            audio_base = carregar_wav(base_wav)
            prog = Progresso("diarização")
            try:
                dia = diarizar(audio_base, op.diarizacao, token, op.num_participantes, op.min_participantes,
                               op.max_participantes, op.dispositivo != "cpu", op.limiar_sherpa, prog)
            except Exception as e:
                prog.fim()
                log.error("    Falha na diarização: %s", e)
                log.error("    A transcrição continuará sem identificação de participantes.")
                dia = None
            else:
                prog.fim()
                cache.gravar("diarizacao", k_dia, dia.para_dict())
            del audio_base
            tempos["diarização"] = time.time() - t
        if dia is not None:
            log.info("    %d participantes detectados (%s)", len(dia.falantes), dia.backend)
    else:
        _etapa(3, total_etapas, "Diarização desativada")
        k_dia = "nenhuma"

    fala_diar = regioes_de_fala(dia.turnos) if dia else []
    fala_asr = unir(fala_vad + fala_diar)
    fala_ref = fala_diar if dia else fala_vad

    # 4. Reconhecimento (primeiro passo) ----------------------------------------
    from .asr import Reconhecedor, montar_hotwords, montar_prompt, passo1

    rec: Reconhecedor | None = None
    audio_asr = None

    def obter_rec(nome: str) -> Reconhecedor:
        nonlocal rec
        if rec is None or rec.nome != nome:
            if rec is not None:
                rec.liberar()
            log.info("    Carregando o modelo %s (na primeira execução ele é baixado da internet)...", nome)
            rec = Reconhecedor(nome, op.dispositivo, op.precisao)
            log.info("    Modelo pronto em %s (%s)", rec.dispositivo, rec.precisao)
        return rec

    def obter_audio_asr():
        nonlocal audio_asr
        if audio_asr is None:
            audio_asr = carregar_wav(asr_wav)
        return audio_asr

    contexto = (op.contexto or "").strip() or None
    k_p1 = Cache.chave("p1", k_pre, k_dia, op.modelo, op.precisao, op.dispositivo, contexto, op.glossario,
                       op.literal, op.beam)
    c_p1 = cache.ler("passo1", k_p1)
    if c_p1 is not None:
        _etapa(4, total_etapas, "Transcrição do primeiro passo já feita (reaproveitada)")
        segmentos = [SegmentoASR.de_dict(s) for s in c_p1["segmentos"]]
        prompt = c_p1["prompt"]
        hot1 = c_p1["hotwords"]
        dispositivo_usado = c_p1.get("dispositivo", "")
    else:
        t = time.time()
        _etapa(4, total_etapas, "Transcrevendo a fala (primeiro passo, contexto contínuo)")
        r = obter_rec(op.modelo)
        prompt = montar_prompt(r, contexto, op.literal)
        hot1 = montar_hotwords(r, op.glossario)
        prog = Progresso("transcrição")
        segmentos, _trechos = passo1(r, obter_audio_asr(), fala_asr, prompt, hot1, op.beam, prog)
        prog.fim()
        dispositivo_usado = f"{r.dispositivo} ({r.precisao})"
        cache.gravar("passo1", k_p1, {"segmentos": [s.para_dict() for s in segmentos], "prompt": prompt,
                                      "hotwords": hot1, "dispositivo": dispositivo_usado})
        tempos["transcrição"] = time.time() - t

    # Filtro de alucinações e diagnóstico
    palavras: list[Palavra] = []
    alvos: list[tuple[float, float, str]] = []
    alucinacoes: list[dict] = []
    for s in segmentos:
        d = diagnosticar_segmento(s, fala_ref, prompt)
        if d.descartar:
            if s.texto.strip():
                alucinacoes.append({"inicio": round(s.inicio, 2), "fim": round(s.fim, 2), "texto": s.texto.strip(),
                                    "motivo": "; ".join(d.motivos)})
            continue
        palavras.extend(s.palavras)
        if d.revisar:
            alvos.append((s.inicio, s.fim, "; ".join(d.motivos)))
    palavras.sort(key=lambda p: (p.inicio, p.fim))
    log.info("    %d palavras no primeiro passo; %d segmentos para revisar; %d frases descartadas como alucinação",
             len(palavras), len(alvos), len(alucinacoes))

    # 5. Revisão ----------------------------------------------------------------
    estat_rev: dict = {}
    registros: list[dict] = []
    incertezas: list[dict] = []
    if op.revisao and (palavras or fala_ref):
        from .revisao import revisar

        termos = list(op.glossario) + termos_da_reuniao(palavras)
        modelo_rev = op.modelo_revisao or op.modelo
        k_rev = Cache.chave("rev", VERSAO_REVISAO, k_p1, modelo_rev, asdict(op.opcoes_revisao), termos, contexto)
        c_rev = cache.ler("revisao", k_rev)
        if c_rev is not None:
            _etapa(5, total_etapas, "Revisão já feita (reaproveitada)")
            palavras = [Palavra.de_dict(p) for p in c_rev["palavras"]]
            marcadores = [Marcador.de_dict(m) for m in c_rev["marcadores"]]
            registros = c_rev["registros"]
            estat_rev = c_rev["estatisticas"]
        else:
            t = time.time()
            _etapa(5, total_etapas, "Revisando trechos de baixa confiança e falas omitidas (segundo passo)")
            r = obter_rec(modelo_rev)
            hot2 = montar_hotwords(r, termos)
            prog = Progresso("revisão")
            palavras, marcadores, regs, estat_rev = revisar(r, obter_audio_asr(), palavras, alvos, fala_ref, hot2,
                                                            contexto, op.opcoes_revisao, prog, fala_asr)
            prog.fim()
            registros = [x.para_dict() for x in regs]
            cache.gravar("revisao", k_rev, {"palavras": [p.para_dict() for p in palavras],
                                            "marcadores": [m.para_dict() for m in marcadores],
                                            "registros": registros, "estatisticas": estat_rev})
            tempos["revisão"] = time.time() - t
        estat_rev = dict(estat_rev)
        incertezas = estat_rev.pop("incertezas", [])
        alucinacoes += estat_rev.pop("descartadas", [])
        log.info("    %d janelas revisadas (%d com alteração ou sinalização); %d palavras recuperadas; %d incertas",
                 estat_rev.get("janelas", 0), estat_rev.get("alteradas", 0),
                 estat_rev.get("palavras_recuperadas", 0), estat_rev.get("palavras_incertas", 0))
    else:
        _etapa(5, total_etapas, "Revisão desativada")
        marcadores = [Marcador(a, b, "inaudivel") for a, b in lacunas(fala_ref, palavras, op.opcoes_revisao.inaudivel_minimo)]
    if rec is not None:
        rec.liberar()
        rec = None
    audio_asr = None

    # 6. Montagem e exportação ---------------------------------------------------
    t = time.time()
    _etapa(6, total_etapas, "Atribuindo falas aos participantes e gerando os arquivos")
    opm = op.opcoes_montagem
    turnos: list[Turno] = dia.turnos if dia else []
    exclusivos: list[Turno] = dia.exclusivos if dia else []
    if dia:
        infos = atribuir_falantes(palavras, exclusivos, opm, turnos)
        alteradas = suavizar(palavras, infos, opm, turnos)
        log.debug("Suavização alterou %d atribuições", alteradas)
        for m in marcadores:
            if m.tipo == "inaudivel":
                m.falante = falante_em(m.inicio, m.fim, exclusivos)
        marcadores = [m for m in marcadores if m.tipo != "simultanea"] + marcadores_simultaneos(palavras, turnos, opm)
        rotulos = rotular(palavras, marcadores, turnos)
    else:
        for p in palavras:
            p.falante = SEM_DIARIZACAO
        for m in marcadores:
            m.falante = SEM_DIARIZACAO
        rotulos = {SEM_DIARIZACAO: "Fala"}
    marcadores.sort(key=lambda m: m.inicio)

    descricao_asr = (f"Whisper {op.modelo} (faster-whisper), português, "
                     + ("com revisão em segundo passo" if op.revisao else "sem revisão"))
    if op.modelo_revisao and op.revisao:
        descricao_asr += f" (revisão com {op.modelo_revisao})"
    if dia is None:
        descricao_diar = "desativada" if op.diarizacao == "nenhuma" else "falhou (sem identificação de participantes)"
    elif dia.backend == "pyannote":
        descricao_diar = "pyannote speaker-diarization-community-1"
    elif dia.backend == "livre":
        descricao_diar = "pipeline pyannote 3.1 com componentes de acesso livre (segmentação 3.0 + WeSpeaker), sem token"
    else:
        descricao_diar = "sherpa-onnx (segmentação pyannote 3.0 + TitaNet), último recurso sem token"

    observacoes = []
    if dia:
        observacoes += dia.observacoes
    if not palavras:
        observacoes.append("Nenhuma fala foi reconhecida na gravação.")

    tempos["montagem"] = time.time() - t
    dados = {
        "formato": "transcritor/1",
        "versao_programa": __version__,
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "arquivo": {"nome": entrada.name, "caminho": str(entrada), "base": base,
                    "duracao": info.duracao or (len(palavras) and palavras[-1].fim) or 0.0,
                    "faixas_audio": info.faixas_audio},
        "processamento": {
            "descricao_asr": descricao_asr,
            "descricao_diarizacao": descricao_diar,
            "modelo": op.modelo,
            "modelo_revisao": op.modelo_revisao,
            "dispositivo": f"{dispositivo_usado} | GPU: {descrever_gpu()}",
            "contexto": contexto,
            "glossario": op.glossario,
            "prompt": prompt,
            "hotwords": hot1,
            "preprocessamento": pre["resultado"],
            "opcoes_revisao": asdict(op.opcoes_revisao),
            "opcoes_montagem": asdict(opm),
            "tempos_etapas_s": {k: round(v, 1) for k, v in tempos.items()},
            "tempo_total_s": round(time.time() - t_inicio, 1),
        },
        "observacoes": observacoes,
        "falantes": {f: {"rotulo": r, "nome": None} for f, r in rotulos.items()},
        "palavras": [p.para_dict() for p in palavras],
        "marcadores": [m.para_dict() for m in marcadores],
        "diarizacao": dia.para_dict() if dia else None,
        "revisao": {"estatisticas": estat_rev, "incertezas": incertezas, "registros": registros},
        "alucinacoes_removidas": alucinacoes,
    }
    json_saida = pasta / f"{base}.json"
    arquivos = gerar_saidas(dados, pasta, op.formatos, json_saida)
    if not op.manter_audio:
        for f in (base_wav, asr_wav):
            f.unlink(missing_ok=True)
    log.info("")
    log.info("Concluído em %s. Arquivos gerados:", tempo.duracao_legivel(time.time() - t_inicio))
    for a in arquivos:
        log.info("    %s", a)
    return json_saida


def carregar_transcricao(caminho: Path) -> dict:
    dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    if dados.get("formato") != "transcritor/1":
        raise ValueError(f"{caminho} não é um arquivo de transcrição deste programa.")
    return dados


def exibicao(dados: dict) -> dict[str, str]:
    return {f: (info.get("nome") or info["rotulo"]) for f, info in dados["falantes"].items()}


def gerar_saidas(dados: dict, pasta: Path, formatos: list[str], json_saida: Path | None = None) -> list[Path]:
    """Monta os blocos a partir do JSON e grava os formatos pedidos e o relatório."""
    palavras = [Palavra.de_dict(p) for p in dados["palavras"]]
    marcadores = [Marcador.de_dict(m) for m in dados["marcadores"]]
    turnos = [Turno.de_dict(t) for t in (dados.get("diarizacao") or {}).get("turnos", [])]
    exibir = exibicao(dados)
    opm = OpcoesMontagem(**dados["processamento"].get("opcoes_montagem", {}))
    blocos = montar_blocos(palavras, marcadores, turnos, exibir, opm)

    # Participantes na ordem dos rótulos; rótulos com o mesmo nome aparecem juntos.
    def numero(rotulo: str) -> int:
        try:
            return int(rotulo.rsplit(" ", 1)[-1])
        except ValueError:
            return 0

    por_nome: dict[str, list[str]] = {}
    for f, info in sorted(dados["falantes"].items(), key=lambda x: numero(x[1]["rotulo"])):
        por_nome.setdefault(exibir[f], []).append(info["rotulo"])
    participantes = [(", ".join(rots), nome) if nome not in rots else (nome, nome) for nome, rots in por_nome.items()]

    base = dados["arquivo"]["base"]
    doc = exportar.Documento(
        titulo=dados["arquivo"]["nome"],
        arquivo=dados["arquivo"]["nome"],
        duracao=float(dados["arquivo"]["duracao"]),
        gerado_em=dados["gerado_em"],
        descricao_asr=dados["processamento"]["descricao_asr"],
        descricao_diarizacao=dados["processamento"]["descricao_diarizacao"],
        participantes=participantes,
        blocos=blocos,
        palavras=palavras,
        marcadores=marcadores,
        exibir=exibir,
        observacoes=list(dados.get("observacoes", [])),
    )
    dados["blocos"] = [{"inicio": round(b.inicio, 2), "fim": round(b.fim, 2), "falante": b.falante,
                        "texto": texto_bloco(b)} for b in blocos]
    formatos = list(dict.fromkeys(formatos))
    if "json" not in formatos:
        formatos.append("json")  # o JSON é a fonte para renomear e reexportar
    arquivos = exportar.salvar(doc, pasta, base, formatos, dados_json=dados)
    rel = pasta / f"{base}_relatorio.md"
    rel.write_text(relatorio.gerar(dados, exibir, palavras, marcadores), encoding="utf-8")
    arquivos.append(rel)
    return arquivos
