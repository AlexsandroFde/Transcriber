"""Páginas exibidas pela janela antes da interface: abertura (enquanto o serviço inicia) e erro."""

from __future__ import annotations

import html

_ESTILO = """
:root { color-scheme: light dark; --fundo:#f5f5f1; --sup:#fff; --texto:#17181a; --texto2:#4b4f55; --borda:#e2e1da;
  --acento:#0b6e5f; --sobre:#fff; --perigo:#b42318; --perigo-suave:#fdeceb; }
@media (prefers-color-scheme: dark) { :root { --fundo:#111315; --sup:#191c1f; --texto:#eceef0; --texto2:#b5b9be;
  --borda:#2b2f34; --acento:#36b9a0; --sobre:#04201b; --perigo:#f07a6e; --perigo-suave:#3a1714; } }
* { box-sizing: border-box; }
body { margin:0; min-height:100vh; display:grid; place-items:center; background:var(--fundo); color:var(--texto);
  font-family:"Segoe UI Variable Text","Segoe UI",system-ui,sans-serif; -webkit-font-smoothing:antialiased; }
.caixa { display:flex; flex-direction:column; align-items:center; gap:18px; text-align:center; padding:32px; max-width:560px; }
.marca { width:64px; height:64px; border-radius:18px; background:var(--acento); display:grid; place-items:center; }
.marca svg { width:34px; height:34px; stroke:var(--sobre); fill:none; stroke-width:1.9; stroke-linecap:round; }
h1 { margin:0; font-family:"Segoe UI Variable Display","Segoe UI",system-ui,sans-serif; font-size:24px; font-weight:650; }
p { margin:0; color:var(--texto2); line-height:1.55; }
.giro { width:22px; height:22px; border-radius:50%; border:2.5px solid color-mix(in srgb, var(--acento) 25%, transparent);
  border-top-color:var(--acento); animation:g .8s linear infinite; }
@keyframes g { to { transform:rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .giro { animation-duration: 3s; } }
.erro { width:100%; text-align:left; background:var(--perigo-suave); border:1px solid color-mix(in srgb, var(--perigo) 30%, transparent);
  border-radius:12px; padding:14px 16px; color:var(--texto); }
.erro strong { display:block; margin-bottom:4px; }
pre { white-space:pre-wrap; word-break:break-word; font:12px/1.5 "Cascadia Mono",Consolas,monospace; color:var(--texto2);
  margin:10px 0 0; max-height:160px; overflow:auto; }
.acoes { display:flex; gap:10px; flex-wrap:wrap; justify-content:center; }
button { font:inherit; font-weight:600; font-size:14px; min-height:38px; padding:0 16px; border-radius:9px; cursor:pointer;
  border:1px solid var(--borda); background:var(--sup); color:var(--texto); }
button.primario { background:var(--acento); color:var(--sobre); border-color:transparent; }
button:focus-visible { outline:2px solid var(--acento); outline-offset:2px; }
"""

_MARCA = ('<div class="marca" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 10v4M8.5 7v10M12 9.5v5M15 8h5M15 12h5'
          'M15 16h3"/></svg></div>')


def abertura(mensagem: str = "Iniciando o Transcritor...") -> str:
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Transcritor</title>
<style>{_ESTILO}</style></head><body><main class="caixa" role="status" aria-live="polite">{_MARCA}
<h1>Transcritor</h1><div class="giro" aria-hidden="true"></div><p>{html.escape(mensagem)}</p></main></body></html>"""


def erro(titulo: str, mensagem: str, detalhe: str | None, pasta_logs: str) -> str:
    det = f"<pre>{html.escape(detalhe)}</pre>" if detalhe else ""
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Transcritor</title>
<style>{_ESTILO}</style></head><body><main class="caixa">{_MARCA}<h1>{html.escape(titulo)}</h1>
<div class="erro" role="alert"><strong>{html.escape(mensagem)}</strong>
<p>Tente de novo. Se o problema continuar, execute o instalar.bat outra vez, na pasta do programa; os detalhes técnicos
ficam nos registros, em {html.escape(pasta_logs)}.</p>{det}</div>
<div class="acoes"><button class="primario" onclick="window.pywebview.api.tentar_novamente()">Tentar de novo</button>
<button onclick="window.pywebview.api.abrir_registros()">Abrir os registros</button>
<button onclick="window.pywebview.api.fechar()">Fechar</button></div></main></body></html>"""
