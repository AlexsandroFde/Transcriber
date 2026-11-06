"""Proteção da API local contra uso indevido por sites abertos no navegador.

A API roda no computador da pessoa usuária e pode abrir e ler arquivos. Um site qualquer
aberto no navegador poderia tentar chamá-la (CSRF) ou usar um domínio que aponta para
127.0.0.1 (DNS rebinding). Por isso:

  * só são aceitos os nomes de host locais (127.0.0.1, localhost, ::1) e os configurados;
  * pedidos que o navegador marca como vindos de outro site (`Sec-Fetch-Site`) são
    recusados, exceto a navegação direta para uma página (abrir /docs a partir de um link);
  * métodos que alteram dados exigem que a origem, quando informada, seja a própria API.

Programas locais (curl, scripts, outras aplicações) não enviam esses cabeçalhos e seguem
funcionando normalmente.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

HOSTS_LOCAIS = {"127.0.0.1", "localhost", "::1"}
METODOS_SEGUROS = {"GET", "HEAD", "OPTIONS"}


def _nome_host(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("["):  # [::1]:8765
        return host[1:].split("]", 1)[0]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


class ProtecaoLocal:
    def __init__(self, app, hosts_extras: Iterable[str] = (), origens_extras: Iterable[str] = ()) -> None:
        self.app = app
        self.hosts = HOSTS_LOCAIS | {h.lower() for h in hosts_extras}
        self.origens_extras = {o.rstrip("/").lower() for o in origens_extras}

    async def _recusar(self, send, status: int, codigo: str, mensagem: str) -> None:
        corpo = json.dumps({"erro": {"codigo": codigo, "status": status, "mensagem": mensagem, "dica": None,
                                     "campos": []}}, ensure_ascii=False).encode("utf-8")
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json; charset=utf-8"),
                                (b"content-length", str(len(corpo)).encode())]})
        await send({"type": "http.response.body", "body": corpo})

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cab = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        host = cab.get("host", "")
        if _nome_host(host) not in self.hosts:
            await self._recusar(send, 400, "host_nao_permitido", f"Nome de host não permitido: {host}")
            return
        metodo = scope.get("method", "GET").upper()
        site = cab.get("sec-fetch-site", "")
        navegacao = metodo == "GET" and cab.get("sec-fetch-mode") == "navigate"
        origem = cab.get("origin", "").rstrip("/").lower()
        permitida = origem in self.origens_extras
        if site in ("cross-site", "same-site") and not navegacao and not permitida:
            await self._recusar(send, 403, "origem_nao_permitida",
                                "Pedido recusado: ele veio de outro site aberto no navegador.")
            return
        if metodo not in METODOS_SEGUROS and origem and not permitida:
            propria = {f"http://{host.lower()}", f"https://{host.lower()}"}
            if origem not in propria:
                await self._recusar(send, 403, "origem_nao_permitida",
                                    f"Origem não permitida: {origem}. A API só aceita alterações vindas da própria "
                                    "interface ou de programas locais.")
                return
        await self.app(scope, receive, send)
