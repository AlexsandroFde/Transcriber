"""Interface de linha de comando.

Exemplos:
    transcritor reuniao.mp4
    transcritor transcrever reuniao.mp4 -n 4 -c "Reunião do conselho sobre o orçamento 2027" -g glossario.txt
    transcritor nomear reuniao_transcricao/reuniao.json "Participante 1=Ana Souza" "Participante 2=Carlos"
    transcritor exportar reuniao_transcricao/reuniao.json -f docx,srt
    transcritor verificar
    transcritor configurar-token hf_xxxxxxxx
"""

from __future__ import annotations

import argparse
import glob
import logging
import sys
from pathlib import Path

from . import __version__
from .ambiente import configurar_log, preparar

log = logging.getLogger("transcritor")

COMANDOS = {"transcrever", "nomear", "exportar", "verificar", "configurar-token"}


def _formatos(valor: str) -> list[str]:
    from .exportar import FORMATOS

    itens = [v.strip().lower().lstrip(".") for v in valor.split(",") if v.strip()]
    invalidos = [v for v in itens if v not in FORMATOS]
    if invalidos:
        raise argparse.ArgumentTypeError(f"formato(s) inválido(s): {', '.join(invalidos)}. Use: {', '.join(FORMATOS)}")
    return itens


def _ler_glossario(caminho: str | None) -> list[str]:
    if not caminho:
        return []
    termos = []
    for linha in Path(caminho).read_text(encoding="utf-8-sig").splitlines():
        linha = linha.split("#", 1)[0].strip()
        if linha:
            termos.extend(t.strip() for t in linha.split(";") if t.strip())
    return termos


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="transcritor",
        description="Transcrição fiel de reuniões gravadas (português brasileiro), com identificação de "
                    "participantes, marcação temporal e exportação em MD, TXT, DOCX, SRT, VTT e JSON.",
    )
    p.add_argument("--version", action="version", version=f"transcritor {__version__}")
    sub = p.add_subparsers(dest="comando")

    t = sub.add_parser("transcrever", help="transcreve um ou mais vídeos/áudios")
    t.add_argument("entradas", nargs="+", help="arquivos de vídeo ou áudio")
    t.add_argument("-s", "--saida", help="pasta de saída (padrão: <pasta do vídeo>/<nome>_transcricao)")
    t.add_argument("-n", "--participantes", type=int, help="número exato de participantes, se conhecido")
    t.add_argument("--min-participantes", type=int, help="número mínimo de participantes")
    t.add_argument("--max-participantes", type=int, help="número máximo de participantes")
    t.add_argument("-c", "--contexto", help="frase descrevendo a reunião (assunto, organização, projeto)")
    t.add_argument("-g", "--glossario", help="arquivo .txt com nomes, siglas e termos técnicos (um por linha)")
    t.add_argument("-m", "--modelo", default="large-v3", help="modelo Whisper (padrão: large-v3)")
    t.add_argument("--modelo-revisao", help="modelo diferente para o segundo passo (ex.: large-v2)")
    t.add_argument("--dispositivo", choices=["auto", "cuda", "cpu"], default="auto")
    t.add_argument("--precisao", choices=["auto", "float16", "int8_float16", "int8", "float32", "bfloat16"],
                   default="auto", help="tipo numérico do modelo (padrão: float16 na GPU, int8 na CPU)")
    t.add_argument("--pre-processamento", choices=["auto", "leve", "forte", "nenhum"], default="auto",
                   help="tratamento do áudio (padrão: auto, que só reduz ruído quando necessário)")
    t.add_argument("--faixa-audio", default="0", help="índice da faixa de áudio ou 'todas' para mixar")
    t.add_argument("--diarizacao", choices=["auto", "pyannote", "livre", "sherpa", "nenhuma"], default="auto",
                   help="identificação de participantes (padrão: pyannote community-1 com token; sem token, "
                        "o pipeline pyannote 3.1 livre)")
    t.add_argument("--hf-token", help="token do Hugging Face (alternativa a configurar-token)")
    t.add_argument("--sem-revisao", action="store_true", help="pula o segundo passo de revisão (mais rápido)")
    t.add_argument("--estilo", choices=["literal", "padrao"], default="literal",
                   help="literal (padrão) preserva hesitações e repetições; padrao deixa o modelo decidir")
    t.add_argument("-f", "--formatos", type=_formatos, default=None,
                   help="formatos de saída separados por vírgula (padrão: md,txt,docx,srt,vtt,json)")
    t.add_argument("--beam", type=int, default=5, help="largura do feixe no primeiro passo (padrão: 5)")
    t.add_argument("--limiar-incerteza", type=float, default=None,
                   help="sem maioria entre as decodificações, palavras abaixo desta probabilidade são marcadas "
                        "como incertas (padrão: 0.85)")
    t.add_argument("--refazer", action="store_true", help="ignora resultados anteriores e processa tudo de novo")
    t.add_argument("--manter-audio", action="store_true", help="mantém os WAV intermediários em .trabalho")
    t.add_argument("-v", "--detalhado", action="store_true", help="mensagens detalhadas")

    n = sub.add_parser("nomear", help="associa nomes aos participantes e regenera os arquivos")
    n.add_argument("json", help="arquivo .json gerado pela transcrição")
    n.add_argument("mapeamentos", nargs="*", help='pares "Participante 1=Nome". Use o mesmo nome para unir dois rótulos')
    n.add_argument("-a", "--arquivo", help="arquivo .txt com um mapeamento por linha")
    n.add_argument("-i", "--interativo", action="store_true",
                   help="pergunta o nome de cada participante, mostrando exemplos de fala e nomes mencionados")
    n.add_argument("--limpar", action="store_true", help="remove todos os nomes atribuídos")
    n.add_argument("-f", "--formatos", type=_formatos, default=None)

    e = sub.add_parser("exportar", help="regenera os arquivos de saída a partir do .json")
    e.add_argument("json")
    e.add_argument("-f", "--formatos", type=_formatos, default=None)
    e.add_argument("-s", "--saida", help="pasta de destino (padrão: a pasta do .json)")

    v = sub.add_parser("verificar", help="verifica GPU, ffmpeg, modelos e token")
    v.add_argument("--baixar-modelos", action="store_true", help="baixa os modelos agora (evita espera depois)")
    v.add_argument("-m", "--modelo", default="large-v3")

    c = sub.add_parser("configurar-token", help="salva o token do Hugging Face para a diarização pyannote")
    c.add_argument("token")
    return p


def _cmd_transcrever(a: argparse.Namespace) -> int:
    from .exportar import FORMATOS
    from .pipeline import Opcoes, processar

    op = Opcoes(
        saida=Path(a.saida) if a.saida else None,
        modelo=a.modelo,
        modelo_revisao=a.modelo_revisao,
        dispositivo=a.dispositivo,
        precisao=a.precisao,
        num_participantes=a.participantes,
        min_participantes=a.min_participantes,
        max_participantes=a.max_participantes,
        contexto=a.contexto,
        glossario=_ler_glossario(a.glossario),
        preprocessamento=a.pre_processamento,
        faixa=a.faixa_audio,
        diarizacao=a.diarizacao,
        hf_token=a.hf_token,
        revisao=not a.sem_revisao,
        literal=a.estilo == "literal",
        formatos=a.formatos or list(FORMATOS),
        refazer=a.refazer,
        manter_audio=a.manter_audio,
        beam=a.beam,
        detalhado=a.detalhado,
    )
    if a.limiar_incerteza is not None:
        op.opcoes_revisao.limiar_sem_maioria = a.limiar_incerteza
    entradas: list[str] = []
    for e in a.entradas:
        # O cmd do Windows não expande curingas (*.mp4); expandimos aqui.
        achados = sorted(glob.glob(e)) if any(c in e for c in "*?[") else [e]
        if not achados:
            log.error("Nenhum arquivo corresponde a: %s", e)
        entradas.extend(achados)
    falhas = 0
    for entrada in entradas:
        try:
            processar(Path(entrada), op)
        except KeyboardInterrupt:
            log.error("\nInterrompido. Os resultados parciais ficam em .trabalho e serão reaproveitados.")
            return 130
        except Exception as e:
            falhas += 1
            log.exception("Erro ao processar %s: %s", entrada, e)
    return 1 if falhas else 0


def _ler_mapeamentos(itens: list[str], arquivo: str | None) -> list[tuple[str, str]]:
    linhas = list(itens)
    if arquivo:
        linhas += [l for l in Path(arquivo).read_text(encoding="utf-8-sig").splitlines() if l.strip() and not l.startswith("#")]
    pares = []
    for l in linhas:
        if "=" not in l:
            raise SystemExit(f'Mapeamento inválido: "{l}". Use o formato "Participante 1=Nome".')
        k, v = l.split("=", 1)
        pares.append((k.strip(), v.strip()))
    return pares


def _perguntar_nomes(dados: dict) -> list[tuple[str, str]]:
    """Mostra cada participante com exemplos de fala e nomes mencionados; pergunta o nome."""
    from collections import Counter

    from . import tempo
    from .modelos import Palavra
    from .nomes import sugerir
    from .relatorio import frases_com_tempo

    palavras = [Palavra.de_dict(p) for p in dados["palavras"]]
    frases = frases_com_tempo(palavras)
    evidencias = sugerir(frases)
    pares = []

    def numero(item):
        try:
            return int(item[1]["rotulo"].rsplit(" ", 1)[-1])
        except ValueError:
            return 0

    print("\nPara cada participante, digite o nome (Enter mantém como está).")
    print("Para unir dois rótulos da mesma pessoa, digite o rótulo da outra (ex.: Participante 1).")
    for f, info in sorted(dados["falantes"].items(), key=numero):
        fala = sum(p.fim - p.inicio for p in palavras if p.falante == f)
        print(f"\n{info['rotulo']} ({tempo.duracao_legivel(fala)} de fala)")
        exemplos = [(t, tx) for t, _fim, ff, tx in frases if ff == f and len(tx.split()) >= 4][:3]
        for t, tx in exemplos:
            print(f"   [{tempo.hms(t)}] {tx[:110]}{'...' if len(tx) > 110 else ''}")
        sugestoes = Counter(e.nome for e in evidencias if e.falante == f).most_common(3)
        if sugestoes:
            print("   Nomes mencionados na fala (confirme antes de usar): "
                  + ", ".join(f"{n} ({c}x)" for n, c in sugestoes))
        atual = info.get("nome") or info["rotulo"]
        try:
            resposta = input(f"   Nome [{atual}]: ").strip()
        except EOFError:
            resposta = ""
        if resposta:
            pares.append((info["rotulo"], resposta))
    return pares


def _cmd_nomear(a: argparse.Namespace) -> int:
    from .exportar import FORMATOS
    from .pipeline import carregar_transcricao, gerar_saidas

    caminho = Path(a.json)
    dados = carregar_transcricao(caminho)
    falantes = dados["falantes"]
    if a.limpar:
        for info in falantes.values():
            info["nome"] = None
    por_chave = {}
    for f, info in falantes.items():
        por_chave[f.lower()] = f
        por_chave[info["rotulo"].lower()] = f
    pares = _ler_mapeamentos(a.mapeamentos, a.arquivo)
    if a.interativo:
        pares += _perguntar_nomes(dados)
    for chave, nome in pares:
        f = por_chave.get(chave.lower())
        if f is None:
            disponiveis = ", ".join(i["rotulo"] for i in falantes.values())
            raise SystemExit(f'Participante "{chave}" não encontrado. Disponíveis: {disponiveis}')
        # Nome igual a outro rótulo une os dois (ex.: "Participante 3=Participante 1").
        alvo = por_chave.get(nome.lower())
        if alvo is not None and alvo != f:
            nome = falantes[alvo]["nome"] or falantes[alvo]["rotulo"]
        falantes[f]["nome"] = nome or None
        log.info("%s -> %s", falantes[f]["rotulo"], nome or "(sem nome)")
    arquivos = gerar_saidas(dados, caminho.parent, a.formatos or list(FORMATOS))
    log.info("Arquivos atualizados:")
    for arq in arquivos:
        log.info("    %s", arq)
    return 0


def _cmd_exportar(a: argparse.Namespace) -> int:
    from .exportar import FORMATOS
    from .pipeline import carregar_transcricao, gerar_saidas

    caminho = Path(a.json)
    dados = carregar_transcricao(caminho)
    pasta = Path(a.saida) if a.saida else caminho.parent
    for arq in gerar_saidas(dados, pasta, a.formatos or list(FORMATOS)):
        log.info("    %s", arq)
    return 0


def _cmd_verificar(a: argparse.Namespace) -> int:
    from .ambiente import caminho_ffmpeg, cuda_disponivel, descrever_gpu, token_hf

    ok = True
    log.info("transcritor %s | Python %s", __version__, sys.version.split()[0])
    try:
        log.info("ffmpeg: %s", caminho_ffmpeg())
    except Exception as e:
        ok = False
        log.error("ffmpeg: não encontrado (%s)", e)
    gpu = cuda_disponivel()
    log.info("GPU (CUDA): %s", descrever_gpu() if gpu else "indisponível; o processamento usará a CPU (bem mais lento)")
    token = token_hf()
    if token:
        log.info("Token do Hugging Face: configurado")
        try:
            from huggingface_hub import HfApi

            from .diarizacao import MODELO_PYANNOTE, PAGINA_MODELO

            try:
                HfApi().model_info(MODELO_PYANNOTE, token=token, files_metadata=False)
                from huggingface_hub import hf_hub_download

                hf_hub_download(MODELO_PYANNOTE, "config.yaml", token=token)
                log.info("Acesso ao modelo de diarização %s: ok", MODELO_PYANNOTE)
            except Exception as e:
                ok = False
                log.error("Sem acesso a %s: %s\n  Aceite os termos em %s com a mesma conta do token.",
                          MODELO_PYANNOTE, str(e).splitlines()[0], PAGINA_MODELO)
        except Exception as e:
            log.error("Não foi possível verificar o acesso ao Hugging Face: %s", e)
    else:
        from .diarizacao import PAGINA_MODELO

        log.info("Token do Hugging Face: não configurado (opcional). A diarização usará o pipeline\n"
                 "  pyannote 3.1 com componentes de acesso livre. Para usar o modelo mais recente\n"
                 "  (community-1): crie uma conta em huggingface.co, aceite os termos em\n"
                 "  %s, gere um token de leitura e rode: transcritor configurar-token SEU_TOKEN", PAGINA_MODELO)
    if a.baixar_modelos:
        log.info("Baixando/verificando o modelo de reconhecimento %s...", a.modelo)
        from .asr import Reconhecedor

        rec = Reconhecedor(a.modelo)
        log.info("Modelo %s pronto (%s, %s).", a.modelo, rec.dispositivo, rec.precisao)
        rec.liberar()
        log.info("Baixando/verificando os modelos de diarização...")
        from .diarizacao import modelos_livre

        modelos_livre()
        if token:
            from .ambiente import carregar_torch
            from .diarizacao import MODELO_PYANNOTE

            carregar_torch()
            from pyannote.audio import Pipeline

            if Pipeline.from_pretrained(MODELO_PYANNOTE, token=token) is not None:
                log.info("Modelo %s pronto.", MODELO_PYANNOTE)
    return 0 if ok else 1


def _cmd_token(a: argparse.Namespace) -> int:
    from .ambiente import salvar_token

    destino = salvar_token(a.token)
    log.info("Token salvo em %s", destino)
    log.info("Rode 'transcritor verificar' para testar o acesso ao modelo de diarização.")
    return 0


def main(argv: list[str] | None = None) -> None:
    preparar()
    configurar_log()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in COMANDOS and not argv[0].startswith("-"):
        argv.insert(0, "transcrever")
    parser = _parser()
    a = parser.parse_args(argv)
    if not a.comando:
        parser.print_help()
        sys.exit(0)
    acoes = {"transcrever": _cmd_transcrever, "nomear": _cmd_nomear, "exportar": _cmd_exportar,
             "verificar": _cmd_verificar, "configurar-token": _cmd_token}
    sys.exit(acoes[a.comando](a))
