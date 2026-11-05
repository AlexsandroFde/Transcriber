"""Gera uma reunião sintética (vídeo MP4) com gabarito, para testar o transcritor.

Usa vozes neurais (edge-tts, requer internet). Inclui situações difíceis de reuniões reais:
hesitações e repetições, interrupção com sobreposição, respostas curtas, siglas, valores,
datas, um participante com volume baixo, ruído de fundo e um silêncio longo.

Uso:
    uv run python ferramentas/gerar_reuniao_teste.py amostras
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

TAXA = 24000
VOZES = {
    "Mariana": "pt-BR-FranciscaNeural",
    "Roberto": "pt-BR-AntonioNeural",
    "Juliana": "pt-BR-ThalitaMultilingualNeural",
    "Carlos": "en-US-AndrewMultilingualNeural",
}
GANHO_DB = {"Mariana": 0.0, "Roberto": -2.0, "Juliana": 0.0, "Carlos": -8.0}  # Carlos longe do microfone

# (falante, texto, intervalo antes em segundos; negativo = começa antes do fim da fala anterior)
ROTEIRO = [
    ("Mariana", "Bom dia a todos. Aqui é a Mariana, da coordenação de projetos. Vamos começar a reunião de "
                "acompanhamento do projeto Iracema Digital.", 1.0),
    ("Roberto", "Bom dia, Mariana.", 0.6),
    ("Mariana", "O primeiro ponto da pauta é a integração com o SIGEP. Roberto, você pode atualizar a gente sobre "
                "o andamento?", 0.5),
    ("Roberto", "Posso sim. Então, a gente, a gente terminou a primeira fase da integração na semana passada. "
                "A API do SIGEP já está respondendo, mas ainda tem um problema de autenticação que a gente precisa "
                "resolver.", 0.7),
    ("Mariana", "E qual seria o prazo para resolver isso?", 0.5),
    ("Roberto", "Eu acho que até o dia 15 de dezembro dá para entregar, se o fornecedor liberar o acesso de "
                "homologação.", 0.6),
    ("Juliana", "Desculpa interromper, mas isso impacta o orçamento?", -0.9),
    ("Roberto", "Não, não, isso já estava previsto no contrato.", 0.4),
    ("Juliana", "Certo.", 0.5),
    ("Mariana", "Juliana, como está a parte financeira?", 0.8),
    ("Juliana", "Então, do total de 450 mil reais aprovados para este ano, a gente já executou cerca de 62 por "
                "cento. Sobram aproximadamente 171 mil reais para o último trimestre.", 0.7),
    ("Carlos", "E desse valor, quanto está reservado para a campanha de comunicação?", 0.6),
    ("Juliana", "Para a campanha, a gente separou 35 mil reais, mas ainda depende da aprovação do conselho.", 0.5),
    ("Mariana", "Bom, então ficou decidido o seguinte: o Roberto fica responsável pela autenticação do SIGEP, com "
                "prazo até 15 de dezembro. A Juliana vai preparar o relatório financeiro para a reunião do conselho, "
                "que vai ser na quinta-feira, às 14 horas.", 8.0),
    ("Carlos", "Só uma coisa: a gente precisa considerar a LGPD na campanha, porque vamos usar os dados dos "
               "beneficiários.", 0.6),
    ("Mariana", "Bem lembrado, Carlos. Você pode levantar isso com o jurídico até sexta-feira?", 0.5),
    ("Carlos", "Posso, sim. Eu mando um e-mail hoje mesmo.", 0.6),
    ("Roberto", "Exato.", 0.3),
    ("Mariana", "Mais algum ponto? Não? Então está encerrada a reunião. Obrigada a todos.", 1.2),
]


async def _sintetizar(texto: str, voz: str, destino: Path, tentativas: int = 4) -> None:
    import edge_tts

    for n in range(tentativas):
        try:
            await edge_tts.Communicate(texto, voz).save(str(destino))
            if destino.stat().st_size > 0:
                return
        except Exception as e:  # serviço online às vezes falha de forma transitória
            if n == tentativas - 1:
                raise
            print(f"  nova tentativa ({voz}): {type(e).__name__}")
        await asyncio.sleep(2 * (n + 1))
    raise RuntimeError(f"Sem áudio para: {texto[:40]}")


def _ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _decodificar(mp3: Path) -> np.ndarray:
    cmd = [_ffmpeg(), "-v", "error", "-i", str(mp3), "-f", "f32le", "-ac", "1", "-ar", str(TAXA), "-"]
    bruto = subprocess.run(cmd, capture_output=True, check=True).stdout
    x = np.frombuffer(bruto, dtype=np.float32).copy()
    # remove silêncio inicial/final do TTS para controlar os intervalos
    ativo = np.where(np.abs(x) > 0.01)[0]
    return x[max(0, ativo[0] - 240) : ativo[-1] + 240] if len(ativo) else x


def main(pasta: Path) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    cache = pasta / "tts"
    cache.mkdir(exist_ok=True)
    trechos = []
    for i, (falante, texto, _) in enumerate(ROTEIRO):
        mp3 = cache / f"{i:02d}_{falante}.mp3"
        if not mp3.exists() or mp3.stat().st_size == 0:
            asyncio.run(_sintetizar(texto, VOZES[falante], mp3))
        x = _decodificar(mp3) * (10 ** (GANHO_DB[falante] / 20))
        trechos.append(x.astype(np.float32))

    t = 0.0
    gabarito = []
    for (falante, texto, intervalo), x in zip(ROTEIRO, trechos):
        inicio = max(0.0, t + intervalo) if gabarito else intervalo
        gabarito.append({"inicio": round(inicio, 3), "fim": round(inicio + len(x) / TAXA, 3),
                         "falante": falante, "texto": texto})
        t = inicio + len(x) / TAXA
    duracao = t + 2.0
    mix = np.zeros(int(duracao * TAXA) + 1, dtype=np.float32)
    for g, x in zip(gabarito, trechos):
        a = int(g["inicio"] * TAXA)
        mix[a : a + len(x)] += x
    rng = np.random.default_rng(7)
    branco = rng.standard_normal(len(mix)).astype(np.float32)
    rosa = np.cumsum(branco)  # ruído grave (tipo ar-condicionado), filtrado para não divergir
    rosa = rosa - np.convolve(rosa, np.ones(2400) / 2400, mode="same")
    ruido = 0.6 * rosa / (np.std(rosa) + 1e-9) + 0.4 * branco
    mix += (10 ** (-48 / 20)) * ruido / np.std(ruido)
    mix *= 0.5 / max(1e-6, float(np.max(np.abs(mix))))

    wav = pasta / "reuniao_teste.wav"
    import soundfile as sf

    sf.write(str(wav), mix, TAXA, subtype="PCM_16")
    mp4 = pasta / "reuniao_teste.mp4"
    cmd = [_ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=640x360:r=5", "-i", str(wav),
           "-shortest", "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-c:a", "aac",
           "-b:a", "128k", str(mp4)]
    subprocess.run(cmd, check=True)
    (pasta / "reuniao_teste_gabarito.json").write_text(json.dumps(gabarito, ensure_ascii=False, indent=1),
                                                       encoding="utf-8")
    print(f"Gerado {mp4} ({duracao:.1f} s) e gabarito com {len(gabarito)} falas.")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "amostras"))
