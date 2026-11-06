import { api } from "../api.js";
import { html, useEffect, useState } from "../biblioteca.js";
import { Botao, Campo, Carregando, Interruptor, PainelErro, confirmar, executar, notificar, useAtraso, useTitulo } from "../componentes.js";
import { abrirNoNavegador } from "../desktop.js";
import { dataHora, plural } from "../formato.js";
import { Icone } from "../icones.js";
import { ativa, guardarTarefa, ir, preferencia, salvarPreferencia, useLoja } from "../loja.js";
import { CartaoTarefa } from "../pecas.js";

export function aplicarTema(tema) {
  const escuro = tema === "escuro" || (tema === "sistema" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-tema", escuro ? "escuro" : "claro");
}

function Linha({ estado, titulo, texto, acoes }) {
  const icone = { ok: "ok", atencao: "alerta", erro: "fechar", neutro: "info" }[estado];
  return html`<li class=${estado}>
    <span class="simbolo"><${Icone} nome=${icone} /></span>
    <span class="corpo"><strong>${titulo}</strong>${texto && html`<span>${texto}</span>`}</span>
    ${acoes}
  </li>`;
}

function SecaoAmbiente() {
  const ambiente = useLoja((e) => e.ambiente);
  const tarefas = useLoja((e) => e.tarefas);
  const download = [...tarefas.values()].find((t) => t.tipo === "download_modelos" && ativa(t));
  const rel = ambiente && ambiente.relatorio;
  const verificando = ambiente && ambiente.situacao === "verificando";

  async function verificar() {
    const t = await executar(() => api.verificarAmbiente(), "Não foi possível verificar o ambiente");
    if (t) guardarTarefa(t);
  }
  async function baixar() {
    const t = await executar(() => api.baixarModelos(), "Não foi possível iniciar o download");
    if (t) guardarTarefa(t);
  }

  let linhas = null;
  if (rel) {
    const tk = rel.token_hf;
    const estadoToken = { ok: "ok", negado: "erro", erro: "atencao", sem_token: "neutro", nao_verificado: "neutro" }[tk.acesso_modelo];
    const textoToken = { ok: "Acesso liberado ao modelo mais recente de identificação de participantes (community-1).",
      negado: "O token não dá acesso ao modelo community-1. Confira se os termos foram aceitos com a mesma conta. Enquanto isso, é usado o pipeline livre.",
      erro: "Não foi possível verificar o acesso agora (sem conexão com a internet?).",
      sem_token: "Opcional. Sem token, a identificação usa o pipeline pyannote 3.1 de acesso livre." }[tk.acesso_modelo];
    linhas = [
      html`<${Linha} estado=${rel.gpu.disponivel ? "ok" : "atencao"} titulo=${rel.gpu.disponivel ? `Placa de vídeo: ${rel.gpu.descricao}` : "Sem placa de vídeo compatível"}
        texto=${rel.gpu.disponivel ? "A transcrição usa a placa de vídeo (rápido)." : "A transcrição usa o processador: cerca de 10 vezes mais lenta."} />`,
      html`<${Linha} estado=${rel.ffmpeg.disponivel ? "ok" : "erro"} titulo=${rel.ffmpeg.disponivel ? "Leitura de áudio e vídeo (ffmpeg)" : "ffmpeg não encontrado"}
        texto=${rel.ffmpeg.disponivel ? rel.ffmpeg.caminho : "Reinstale o Transcritor executando o instalar.bat."} />`,
      ...rel.modelos.map((m) => html`<${Linha} estado=${m.baixado ? "ok" : m.baixado === false ? (m.obrigatorio ? "atencao" : "neutro") : "neutro"}
        titulo=${m.nome} texto=${m.baixado ? `Baixado. ${m.descricao}` : m.baixado === false ? `Ainda não baixado: será baixado na primeira transcrição. ${m.descricao}` : m.descricao} />`),
      html`<${Linha} estado=${estadoToken} titulo=${tk.configurado ? "Token do Hugging Face configurado" : "Token do Hugging Face (opcional)"} texto=${textoToken} />`,
    ];
  }
  const faltam = rel && rel.modelos.some((m) => m.baixado === false);

  return html`<section class="secao" id="ambiente" aria-labelledby="t-ambiente">
    <div class="secao-cabecalho">
      <h2 id="t-ambiente">Ambiente</h2>
      <div class="acoes">
        <${Botao} tamanho="pequeno" icone="repetir" carregando=${verificando} onClick=${verificar}>${verificando ? "Verificando..." : "Verificar de novo"}</${Botao}>
        ${faltam && !download && html`<${Botao} tamanho="pequeno" icone="baixar" onClick=${baixar}>Baixar modelos agora</${Botao}>`}
      </div>
    </div>
    ${download && html`<div style="margin-bottom:12px"><${CartaoTarefa} tarefa=${download} /></div>`}
    <div class="cartao">
      ${!rel ? html`<div class="cartao-corpo"><${Carregando} texto="Verificando placa de vídeo, ffmpeg, modelos e token..." /></div>`
        : html`<ul class="estado-lista">${linhas}</ul>`}
    </div>
    ${rel && html`<p class="ajuda" style="margin-top:8px">Verificado em ${dataHora(rel.verificado_em)} · Transcritor ${rel.versao} · Python ${rel.python}</p>`}
  </section>`;
}

function SecaoToken() {
  const [estado, setEstado] = useState(null);
  const [erro, setErro] = useState(null);
  const [token, setToken] = useState("");
  const [mostrar, setMostrar] = useState(false);
  const [salvando, setSalvando] = useState(false);

  const carregar = () => api.token().then(setEstado).catch(setErro);
  useEffect(() => { carregar(); }, []);

  async function salvar() {
    setErro(null);
    setSalvando(true);
    try {
      setEstado(await api.salvarToken(token.trim()));
      setToken("");
      notificar({ titulo: "Token salvo", mensagem: "Verificando o acesso ao modelo community-1..." });
      const t = await api.verificarAmbiente();
      guardarTarefa(t);
    } catch (e) {
      setErro(e);
    } finally {
      setSalvando(false);
    }
  }

  async function remover() {
    const ok = await confirmar({ titulo: "Remover o token?", mensagem: "A identificação de participantes passa a usar o pipeline de acesso livre.",
      confirmar: "Remover token", perigo: true });
    if (!ok) return;
    try {
      setEstado(await api.removerToken());
      notificar({ titulo: "Token removido" });
      guardarTarefa(await api.verificarAmbiente());
    } catch (e) {
      setErro(e);
    }
  }

  const origem = estado && { arquivo: "salvo pelo Transcritor", variavel_ambiente: `variável de ambiente ${estado.variavel || ""}`,
    login_huggingface: "login do Hugging Face neste computador" }[estado.origem];
  const link = (url, texto) => html`<button type="button" class="ligacao" onClick=${() => abrirNoNavegador(url)}>${texto}</button>`;

  return html`<section class="secao" id="hugging-face" aria-labelledby="t-token">
    <div class="secao-cabecalho"><h2 id="t-token">Identificação avançada de participantes</h2></div>
    <div class="cartao"><div class="grupo-form">
      <p class="texto-2">O Transcritor já identifica os participantes sem nenhuma configuração. O modelo mais recente do pyannote
        (community-1) é gratuito, mas exige uma conta no Hugging Face:</p>
      ${estado ? html`<ol class="passos">
        <li>${link(estado.pagina_cadastro, "Crie uma conta no Hugging Face")}.</li>
        <li>Abra a ${link(estado.pagina_modelo, "página do modelo community-1")} e aceite os termos de uso (botão no topo).</li>
        <li>${link(estado.pagina_tokens, "Gere um token de leitura")} e cole abaixo.</li>
      </ol>` : html`<${Carregando} />`}
      ${estado && estado.configurado && html`<p><${Icone} nome="chave" tamanho=${16} /> Token configurado${estado.final ? `, terminando em ${estado.final}` : ""} (${origem}).</p>`}
      <${Campo} id="token" rotulo=${estado && estado.configurado ? "Substituir o token" : "Token"} erro=${erro && erro.campo("token")}>
        <div class="com-botao">
          <input id="token" class="entrada mono" type=${mostrar ? "text" : "password"} value=${token} autocomplete="off" spellcheck="false"
            placeholder="hf_..." onInput=${(e) => setToken(e.currentTarget.value)} />
          <${Botao} variante="fantasma" icone=${mostrar ? "olho-fechado" : "olho"} rotulo=${mostrar ? "Ocultar o token" : "Mostrar o token"}
            aria-pressed=${mostrar ? "true" : "false"} onClick=${() => setMostrar(!mostrar)} />
          <${Botao} variante="primario" carregando=${salvando} disabled=${token.trim().length < 8} onClick=${salvar}>Salvar</${Botao}>
        </div>
      </${Campo}>
      ${erro && !erro.campo("token") && html`<${PainelErro} erro=${erro} />`}
      ${estado && estado.pode_remover && html`<div><${Botao} variante="perigo" tamanho="pequeno" icone="lixeira" onClick=${remover}>Remover o token salvo</${Botao}></div>`}
      <p class="ajuda">O token fica só neste computador, em ${estado ? html`<span class="mono">${estado.arquivo}</span>` : "..."}, e é usado apenas para baixar o modelo.</p>
    </div></div>
  </section>`;
}

function SecaoGlossario() {
  const [g, setG] = useState(null);
  const [texto, setTexto] = useState("");
  const [termos, setTermos] = useState(null);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState(null);
  useEffect(() => { api.glossario().then((r) => { setG(r); setTexto(r.texto); setTermos(r.termos.length); }).catch(setErro); }, []);
  const atrasado = useAtraso(texto, 350);
  useEffect(() => {
    if (g === null) return;
    api.interpretarGlossario({ texto: atrasado }).then((r) => setTermos(r.termos.length)).catch(() => {});
  }, [atrasado]);

  async function salvar() {
    setSalvando(true);
    setErro(null);
    try {
      const r = await api.salvarGlossario(texto);
      setG(r);
      notificar({ titulo: "Glossário padrão salvo", mensagem: plural(r.termos.length, "termo", "termos") });
    } catch (e) {
      setErro(e);
    } finally {
      setSalvando(false);
    }
  }

  return html`<section class="secao" id="glossario" aria-labelledby="t-glossario">
    <div class="secao-cabecalho"><h2 id="t-glossario">Glossário padrão</h2></div>
    <div class="cartao"><div class="grupo-form">
      <p class="texto-2">Sugerido em toda transcrição nova (dá para ajustar em cada uma). Inclua nomes de pessoas, da organização,
        de projetos, siglas e termos técnicos: um por linha, ou vários separados por ponto e vírgula. Linhas começando com # são ignoradas.</p>
      ${g === null && !erro ? html`<${Carregando} />` : html`
        <${Campo} id="glossario-padrao" rotulo="Termos" ajuda=${termos !== null ? `${plural(termos, "termo reconhecido", "termos reconhecidos")}.` : null}>
          <textarea id="glossario-padrao" class="entrada mono" rows="8" value=${texto} onInput=${(e) => setTexto(e.currentTarget.value)}
            placeholder=${"# Pessoas\nMariana; Roberto\n# Siglas\nSIGEP; LGPD"} aria-describedby="glossario-padrao-ajuda"></textarea>
        </${Campo}>
        <${PainelErro} erro=${erro} />
        <div class="acoes">
          <${Botao} variante="primario" carregando=${salvando} disabled=${g && texto === g.texto} onClick=${salvar}>Salvar glossário</${Botao}>
          ${g && html`<span class="ajuda">Arquivo: <span class="mono">${g.caminho}</span></span>`}
        </div>`}
    </div></div>
  </section>`;
}

function SecaoPreferencias() {
  const [tema, setTema] = useState(preferencia("tema", "sistema"));
  const [abrirPasta, setAbrirPasta] = useState(preferencia("abrirPasta", false));
  const escolher = (t) => { setTema(t); salvarPreferencia("tema", t); aplicarTema(t); };
  const opcoes = [["sistema", "monitor", "Sistema"], ["claro", "sol", "Claro"], ["escuro", "lua", "Escuro"]];
  return html`<section class="secao" id="preferencias" aria-labelledby="t-preferencias">
    <div class="secao-cabecalho"><h2 id="t-preferencias">Preferências</h2></div>
    <div class="cartao"><div class="grupo-form">
      <div class="interruptor" style="cursor:default">
        <span class="corpo"><span class="titulo" id="rotulo-tema">Aparência</span><span class="descricao">"Sistema" acompanha o tema do Windows.</span></span>
        <div class="segmentado" role="group" aria-labelledby="rotulo-tema">
          ${opcoes.map(([v, ic, r]) => html`<button type="button" aria-pressed=${tema === v ? "true" : "false"} onClick=${() => escolher(v)}>
            <${Icone} nome=${ic} />${r}</button>`)}
        </div>
      </div>
      <${Interruptor} titulo="Abrir a pasta dos arquivos ao concluir uma transcrição" marcado=${abrirPasta}
        descricao="Como fazia o transcrever.bat. Os resultados também ficam disponíveis aqui, em Transcrições."
        aoMudar=${(v) => { setAbrirPasta(v); salvarPreferencia("abrirPasta", v); }} />
    </div></div>
  </section>`;
}

function SecaoSobre() {
  const sistema = useLoja((e) => e.sistema);
  if (!sistema) return null;
  const pastas = [["Registros (logs)", sistema.pastas.logs], ["Dados do aplicativo", sistema.pastas.dados],
    ["Configuração", sistema.pastas.config], ["Modelos de identificação", sistema.pastas.modelos]];
  return html`<section class="secao" id="sobre" aria-labelledby="t-sobre">
    <div class="secao-cabecalho"><h2 id="t-sobre">Sobre e integrações</h2></div>
    <div class="cartao"><div class="grupo-form">
      <dl class="pares">
        <dt>Versão</dt><dd>Transcritor ${sistema.versao} · Python ${sistema.python}</dd>
        <dt>Sistema</dt><dd>${sistema.plataforma}</dd>
        <dt>API REST</dt><dd><span class="mono">${location.origin}/api/v1</span></dd>
      </dl>
      <div class="acoes">
        <${Botao} icone="codigo" onClick=${() => abrirNoNavegador("/docs")}>Documentação da API</${Botao}>
      </div>
      <p class="ajuda">Outros programas podem usar todas as funções do Transcritor pela API: a documentação mostra cada operação, com exemplos,
        e permite testar no navegador.</p>
    </div>
    <ul class="estado-lista" style="border-top:1px solid var(--borda)">
      ${pastas.map(([rotulo, caminho]) => html`<li class="neutro">
        <span class="simbolo"><${Icone} nome="pasta" /></span>
        <span class="corpo"><strong>${rotulo}</strong><span class="mono">${caminho}</span></span>
        <${Botao} tamanho="pequeno" onClick=${() => executar(() => api.abrir(caminho), "A pasta ainda não existe")}>Abrir</${Botao}>
      </li>`)}
    </ul></div>
  </section>`;
}

export function TelaConfiguracoes({ secao }) {
  useTitulo("Configurações");
  useEffect(() => {
    if (!secao) return;
    const t = setTimeout(() => {
      const el = document.getElementById(secao);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 60);
    return () => clearTimeout(t);
  }, [secao]);
  return html`<div class="conteudo estreito">
    <header class="cabecalho"><div class="titulos"><h1>Configurações</h1>
      <p class="subtitulo">Situação do computador, identificação de participantes, glossário e aparência.</p></div></header>
    <nav class="indice-config" aria-label="Seções">
      ${[["ambiente", "Ambiente"], ["hugging-face", "Hugging Face"], ["glossario", "Glossário"], ["preferencias", "Preferências"], ["sobre", "Sobre"]]
        .map(([id, r]) => html`<a href=${`#/configuracoes/${id}`} onClick=${(e) => { e.preventDefault(); ir(`/configuracoes/${id}`);
          const el = document.getElementById(id); if (el) el.scrollIntoView({ behavior: "smooth", block: "start" }); }}>${r}</a>`)}
    </nav>
    <${SecaoAmbiente} />
    <${SecaoToken} />
    <${SecaoGlossario} />
    <${SecaoPreferencias} />
    <${SecaoSobre} />
  </div>`;
}
