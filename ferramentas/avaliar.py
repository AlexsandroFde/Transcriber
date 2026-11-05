"""Compara uma transcrição (.json do transcritor) com um gabarito.

Métricas:
  * WER (taxa de erro de palavras) sobre o texto completo, sem pontuação e sem maiúsculas.
  * Atribuição de falantes: fração das palavras corretamente atribuídas, após mapear cada
    rótulo do sistema ao participante real com quem mais coincide no tempo.

Uso:
    uv run python ferramentas/avaliar.py saida/reuniao_teste.json amostras/reuniao_teste_gabarito.json
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path


def normalizar(texto: str) -> list[str]:
    t = texto.lower()
    t = re.sub(r"\[trecho incerto: ([^\]]*)\]", r"\1", t)
    t = re.sub(r"\[[^\]]*\]", " ", t)
    t = t.replace("r$", " ").replace("%", " por cento")
    t = re.sub(r"(\d)\.(\d{3})", r"\1\2", t)
    t = re.sub(r"[^\w\s]", " ", t)
    t = unicodedata.normalize("NFC", t)
    return t.split()


def main(transcricao: Path, gabarito: Path) -> None:
    import jiwer

    dados = json.loads(transcricao.read_text(encoding="utf-8"))
    ref = json.loads(gabarito.read_text(encoding="utf-8"))
    palavras = dados["palavras"]

    texto_ref = " ".join(" ".join(normalizar(r["texto"])) for r in ref)
    texto_hip = " ".join(" ".join(normalizar(p["texto"])) for p in palavras)
    saida = jiwer.process_words(texto_ref, texto_hip)
    print(f"WER: {100 * saida.wer:.2f}%  (substituições {saida.substitutions}, omissões {saida.deletions}, "
          f"inserções {saida.insertions}, referência {len(texto_ref.split())} palavras)")
    alinh = jiwer.visualize_alignment(saida, show_measures=False)
    erros = [l for l in alinh.splitlines() if l.strip()]
    print("\n".join(erros[:60]))

    # Atribuição de falantes: palavras cujo meio cai em uma fala do gabarito sem sobreposição.
    def falante_ref(t: float) -> str | None:
        ativos = [r["falante"] for r in ref if r["inicio"] <= t <= r["fim"]]
        return ativos[0] if len(ativos) == 1 else None

    coincid: dict[str, Counter] = defaultdict(Counter)
    pares = []
    for p in palavras:
        m = (p["inicio"] + p["fim"]) / 2
        r = falante_ref(m)
        if r is None or p["falante"] is None:
            continue
        coincid[p["falante"]][r] += 1
        pares.append((p["falante"], r))
    mapa = {h: c.most_common(1)[0][0] for h, c in coincid.items()}
    acertos = sum(1 for h, r in pares if mapa.get(h) == r)
    rotulos = {f: i["rotulo"] for f, i in dados["falantes"].items()}
    print(f"\nAtribuição de falantes: {100 * acertos / max(1, len(pares)):.1f}% de {len(pares)} palavras")
    for h, r in sorted(mapa.items(), key=lambda x: rotulos.get(x[0], x[0])):
        print(f"  {rotulos.get(h, h)} -> {r}  {dict(coincid[h])}")
    reais = {r["falante"] for r in ref}
    print(f"Participantes reais: {len(reais)} | detectados: {len(dados['falantes'])}")
    marc = Counter(m["tipo"] for m in dados["marcadores"])
    incertas = sum(1 for p in palavras if p.get("incerta"))
    print(f"Marcadores: {dict(marc)} | palavras incertas: {incertas}")
    print(f"Alucinações removidas: {[a['texto'] for a in dados.get('alucinacoes_removidas', [])]}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
