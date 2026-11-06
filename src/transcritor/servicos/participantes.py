"""Participantes: resumo para identificação e atribuição de nomes (antes o comando `nomear`).

O programa nunca atribui nomes por conta própria. Para cada participante são reunidos o
tempo de fala, exemplos do que a pessoa disse e os nomes mencionados na conversa que
apontam para ela; quem decide é a pessoa usuária.

Regras de atribuição (as mesmas da linha de comando):
  * o participante é localizado pelo rótulo ("Participante 1") ou pela chave interna
    ("SPEAKER_00"), sem diferenciar maiúsculas;
  * nome vazio remove o nome; `limpar` remove todos antes de aplicar as atribuições;
  * nome igual ao rótulo (ou à chave) de outro participante une os dois: o participante
    passa a ser exibido com o nome do outro (a mesma pessoa detectada com dois rótulos).
    As uniões são aplicadas depois dos nomes diretos, então a ordem das atribuições não
    altera o resultado.
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

from ..erros import EntradaInvalida, NaoEncontrado
from ..processamento.documento import exibicao, numero_rotulo
from ..processamento.modelos import Palavra
from ..processamento.nomes import sugerir
from ..processamento.relatorio import frases_com_tempo
from .contratos import AlteracaoNome, ExemploFala, ParticipanteBasico, ParticipanteDetalhe, SugestaoParticipante

log = logging.getLogger("transcritor")


def basicos(dados: dict) -> list[ParticipanteBasico]:
    exibir = exibicao(dados)
    return [ParticipanteBasico(chave=f, rotulo=info["rotulo"], nome=info.get("nome"), exibicao=exibir[f])
            for f, info in sorted(dados["falantes"].items(), key=lambda x: numero_rotulo(x[1]["rotulo"]))]


def resumir(dados: dict, max_exemplos: int = 3, min_palavras_exemplo: int = 4) -> list[ParticipanteDetalhe]:
    """Tempo de fala, exemplos e nomes sugeridos de cada participante, na ordem dos rótulos."""
    palavras = [Palavra.de_dict(p) for p in dados["palavras"]]
    frases = frases_com_tempo(palavras)
    evidencias = sugerir(frases)
    exibir = exibicao(dados)
    saida: list[ParticipanteDetalhe] = []
    for b in basicos(dados):
        proprias = [p for p in palavras if p.falante == b.chave]
        exemplos = [ExemploFala(inicio_s=round(t, 2), texto=tx) for t, _fim, ff, tx in frases
                    if ff == b.chave and len(tx.split()) >= min_palavras_exemplo][:max_exemplos]
        sugestoes = Counter(e.nome for e in evidencias if e.falante == b.chave).most_common(3)
        unidos = [i["rotulo"] for f, i in dados["falantes"].items() if f != b.chave and exibir[f] == b.exibicao]
        saida.append(ParticipanteDetalhe(
            **b.model_dump(), tempo_fala_s=round(sum(p.fim - p.inicio for p in proprias), 2), palavras=len(proprias),
            exemplos=exemplos, sugestoes=[SugestaoParticipante(nome=n, ocorrencias=c) for n, c in sugestoes],
            unido_com=sorted(unidos, key=numero_rotulo)))
    return saida


def ler_mapeamentos(itens: list[str], arquivo: str | Path | None = None) -> list[tuple[str, str]]:
    """Pares "Participante 1=Nome" de argumentos e/ou de um arquivo (linhas com # no início são ignoradas)."""
    linhas = list(itens)
    if arquivo:
        caminho = Path(arquivo).expanduser()
        if not caminho.is_file():
            raise NaoEncontrado(f"Arquivo de mapeamentos não encontrado: {caminho}", codigo="arquivo_nao_encontrado")
        linhas += [l for l in caminho.read_text(encoding="utf-8-sig").splitlines()
                   if l.strip() and not l.startswith("#")]
    pares = []
    for l in linhas:
        if "=" not in l:
            raise EntradaInvalida(f'Mapeamento inválido: "{l}". Use o formato "Participante 1=Nome".',
                                  codigo="mapeamento_invalido")
        k, v = l.split("=", 1)
        pares.append((k.strip(), v.strip()))
    return pares


def aplicar(dados: dict, pares: list[tuple[str, str]], limpar: bool = False) -> list[AlteracaoNome]:
    """Altera `dados["falantes"]` conforme as regras do módulo. Retorna o que mudou."""
    falantes = dados["falantes"]
    antes = {f: info.get("nome") for f, info in falantes.items()}
    if limpar:
        for info in falantes.values():
            info["nome"] = None
    por_chave: dict[str, str] = {}
    for f, info in falantes.items():
        por_chave[f.lower()] = f
        por_chave[info["rotulo"].lower()] = f

    resolvidos: list[tuple[str, str]] = []
    for chave, nome in pares:
        f = por_chave.get(chave.strip().lower())
        if f is None:
            disponiveis = ", ".join(i["rotulo"] for i in falantes.values())
            raise NaoEncontrado(f'Participante "{chave}" não encontrado. Disponíveis: {disponiveis}',
                                codigo="participante_nao_encontrado")
        resolvidos.append((f, nome.strip()))

    def une(f: str, nome: str) -> bool:
        alvo = por_chave.get(nome.lower())
        return alvo is not None and alvo != f

    for f, nome in resolvidos:  # 1º: nomes diretos
        if not une(f, nome):
            falantes[f]["nome"] = nome or None
            log.info("%s -> %s", falantes[f]["rotulo"], nome or "(sem nome)")
    for f, nome in resolvidos:  # 2º: uniões, já com os nomes definitivos
        if une(f, nome):
            alvo = por_chave[nome.lower()]
            falantes[f]["nome"] = falantes[alvo]["nome"] or falantes[alvo]["rotulo"]
            log.info("%s -> %s (unido a %s)", falantes[f]["rotulo"], falantes[f]["nome"], falantes[alvo]["rotulo"])

    return [AlteracaoNome(participante=info["rotulo"], anterior=antes[f], novo=info.get("nome"))
            for f, info in sorted(falantes.items(), key=lambda x: numero_rotulo(x[1]["rotulo"]))
            if antes[f] != info.get("nome")]
