"""Configurações da pessoa usuária: token do Hugging Face e glossário padrão.

O token nunca é devolvido pela API: só se ele existe, de onde vem e os 4 últimos caracteres.
O glossário padrão substitui o `glossario.txt` que o `transcrever.bat` usava automaticamente
(e continua sendo o mesmo arquivo, quando ele existe na pasta do programa).
"""

from __future__ import annotations

from .. import ambiente
from ..config import Configuracoes
from ..erros import Conflito
from . import glossario as glossario_mod
from .contratos import EstadoToken, Glossario

PAGINA_TOKENS = "https://huggingface.co/settings/tokens"
PAGINA_CADASTRO = "https://huggingface.co/join"


class ServicoConfiguracao:
    def __init__(self, config: Configuracoes):
        self.config = config

    # -- token -------------------------------------------------------------

    def estado_token(self) -> EstadoToken:
        from ..processamento.diarizacao import PAGINA_MODELO

        token, origem = ambiente.localizar_token()
        variavel = None
        if origem and origem.startswith("variavel_ambiente:"):
            origem, variavel = "variavel_ambiente", origem.split(":", 1)[1]
        return EstadoToken(
            configurado=bool(token), origem=origem if token else None, variavel=variavel,
            final=token[-4:] if token and len(token) >= 8 else None, arquivo=str(ambiente.arquivo_token()),
            pode_remover=ambiente.arquivo_token().exists(), pagina_modelo=PAGINA_MODELO, pagina_tokens=PAGINA_TOKENS,
            pagina_cadastro=PAGINA_CADASTRO)

    def salvar_token(self, token: str) -> EstadoToken:
        ambiente.salvar_token(token)
        return self.estado_token()

    def remover_token(self) -> EstadoToken:
        if not ambiente.remover_token():
            estado = self.estado_token()
            if estado.origem == "variavel_ambiente":
                raise Conflito(f"O token vem da variável de ambiente {estado.variavel} e não pode ser removido por "
                               "aqui.", codigo="token_externo",
                               dica="Remova a variável de ambiente nas configurações do Windows.")
            if estado.origem == "login_huggingface":
                raise Conflito("O token vem do login do Hugging Face neste computador.", codigo="token_externo",
                               dica="Use o comando `hf auth logout` para sair da conta.")
        return self.estado_token()

    # -- glossário padrão ----------------------------------------------------------

    def glossario(self) -> Glossario:
        arq = self.config.arquivo_glossario
        texto = glossario_mod.ler_texto(arq) if arq.is_file() else ""
        return Glossario(caminho=str(arq), existe=arq.is_file(), texto=texto, termos=glossario_mod.interpretar(texto))

    def salvar_glossario(self, texto: str) -> Glossario:
        arq = self.config.arquivo_glossario
        arq.parent.mkdir(parents=True, exist_ok=True)
        conteudo = texto.replace("\r\n", "\n")
        arq.write_text(conteudo if conteudo.endswith("\n") or not conteudo else conteudo + "\n", encoding="utf-8")
        return self.glossario()
