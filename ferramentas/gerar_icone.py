"""Gera o ícone do aplicativo (src/transcritor/web/icone.ico) a partir do mesmo desenho do favicon.svg.

Uso (só é preciso rodar de novo se o desenho mudar):
    uv run python ferramentas/gerar_icone.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

DESTINO = Path(__file__).resolve().parents[1] / "src" / "transcritor" / "web" / "icone.ico"
ACENTO = (11, 110, 95, 255)
TAMANHOS = [16, 20, 24, 32, 40, 48, 64, 128, 256]

# Mesmo desenho do favicon.svg, numa grade de 64 x 64: ondas de voz que viram linhas de texto.
TRACOS = [((13, 27), (13, 37)), ((21, 20), (21, 44)), ((29, 26), (29, 38)),
          ((38, 23), (51, 23)), ((38, 32), (51, 32)), ((38, 41), (46, 41))]


def desenhar(tamanho: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (tamanho, tamanho), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    e = tamanho / 64
    d.rounded_rectangle([0, 0, tamanho - 1, tamanho - 1], radius=15 * e, fill=ACENTO)
    largura = 5 * e
    for (x1, y1), (x2, y2) in TRACOS:
        d.line([(x1 * e, y1 * e), (x2 * e, y2 * e)], fill="white", width=round(largura))
        for x, y in ((x1, y1), (x2, y2)):  # pontas arredondadas
            r = largura / 2
            d.ellipse([x * e - r, y * e - r, x * e + r, y * e + r], fill="white")
    return img


def main() -> None:
    base = desenhar()
    imagens = [base.resize((t, t), Image.LANCZOS) for t in TAMANHOS]
    imagens[-1].save(DESTINO, format="ICO", sizes=[(t, t) for t in TAMANHOS], append_images=imagens[:-1])
    print(f"Ícone gerado: {DESTINO} ({DESTINO.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
