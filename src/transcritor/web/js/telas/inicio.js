import { api } from "../api.js";
import { html, useState } from "../biblioteca.js";
import { Aviso, Botao, Esqueleto, PainelErro, Vazio, executar, useTitulo } from "../componentes.js";
import { escolherMidias } from "../desktop.js";
import { pct } from "../formato.js";
import { Icone } from "../icones.js";
import { adicionarSelecao, ativa, guardarTarefa, ir, useLoja } from "../loja.js";
import { CartaoTarefa, ItemTranscricao } from "../pecas.js";

export function ZonaArquivos({ compacta = false, aoEscolher }) {
  const [envio, setEnvio] = useState(null);
  const [erro, setErro] = useState(null);

  async function escolher() {
    setErro(null);
    try {
      const caminhos = await escolherMidias((nome, fracao) => setEnvio(nome ? { nome, fracao } : null));
      if (caminhos.length) {
        adicionarSelecao(caminhos);
        if (aoEscolher) aoEscolher(caminhos);
        else ir("/nova");
      }
    } catch (e) {
      setErro(e);
    } finally {
      setEnvio(null);
    }
  }

  return html`<div class="pilha">
    <button type="button" class=${"zona" + (compacta ? " compacta" : "")} onClick=${escolher} disabled=${!!envio}
      aria-describedby="zona-formatos">
      <span class="circulo">${envio ? html`<span class="giro"></span>` : html`<${Icone} nome=${compacta ? "mais" : "enviar"} />`}</span>
      ${envio ? html`<span><strong>Enviando ${envio.nome}</strong><br /><span class="texto-2">${pct(envio.fracao)}</span></span>`
        : compacta ? html`<span><strong>Adicionar arquivos</strong><br /><span class="texto-2">Clique ou arraste para cá</span></span>`
        : html`<span><strong>Arraste um vídeo ou áudio para cá</strong><br /><span class="texto-2">ou clique para escolher no computador</span></span>`}
      ${!compacta && html`<span class="formatos" id="zona-formatos">MP4, MKV, MOV, AVI, MP3, WAV, M4A, OGG e outros formatos de vídeo e áudio</span>`}
    </button>
    <${PainelErro} erro=${erro} titulo="Não foi possível usar o arquivo" />
  </div>`;
}

export function AvisosAmbiente() {
  const ambiente = useLoja((e) => e.ambiente);
  const tarefas = useLoja((e) => e.tarefas);
  const rel = ambiente && ambiente.relatorio;
  if (!rel) return null;
  const download = [...tarefas.values()].find((t) => t.tipo === "download_modelos" && ativa(t));
  const faltando = rel.modelos.filter((m) => m.obrigatorio && m.baixado === false);
  const avisos = [];
  if (!rel.pronto) {
    avisos.push(html`<${Aviso} tipo="erro" titulo="O Transcritor não está pronto para transcrever">
      <p>O componente de leitura de áudio (ffmpeg) não foi encontrado.</p>
      <p class="dica"><b>Como resolver:</b> execute o instalar.bat de novo, na pasta do programa.</p>
    </${Aviso}>`);
  }
  if (faltando.length && !download) {
    avisos.push(html`<${Aviso} tipo="info" titulo="Primeira utilização: os modelos de IA ainda não foram baixados"
      acoes=${html`<${Botao} tamanho="pequeno" icone="baixar" onClick=${async () => {
        const t = await executar(() => api.baixarModelos(), "Não foi possível iniciar o download");
        if (t) { guardarTarefa(t); ir(`/atividades/${t.id}`); }
      }}>Baixar agora</${Botao}>`}>
      <p>Eles têm cerca de 3 GB e são baixados uma única vez, durante a primeira transcrição. Se preferir, baixe agora para não esperar depois.</p>
    </${Aviso}>`);
  }
  if (download) {
    avisos.push(html`<${CartaoTarefa} tarefa=${download} />`);
  }
  if (rel.pronto && !rel.gpu.disponivel) {
    avisos.push(html`<${Aviso} tipo="atencao" titulo="Sem placa de vídeo compatível">
      <p>A transcrição vai usar o processador e será bem mais lenta (cerca de 10 vezes). Em Opções avançadas, o modelo large-v3-turbo é mais rápido.</p>
    </${Aviso}>`);
  }
  return avisos.length ? html`<div class="pilha" style="margin-bottom:22px">${avisos}</div>` : null;
}

export function TelaInicio() {
  useTitulo("Início");
  const tarefas = useLoja((e) => e.tarefas);
  const transcricoes = useLoja((e) => e.transcricoes);
  const ativas = [...tarefas.values()].filter((t) => t.tipo === "transcricao" && ativa(t))
    .sort((a, b) => a.criada_em.localeCompare(b.criada_em));
  const recentes = (transcricoes || []).slice(0, 5);

  return html`<div class="conteudo">
    <header class="cabecalho">
      <div class="titulos">
        <h1>Transcrever uma reunião</h1>
        <p class="subtitulo">Vídeo ou áudio em português. Tudo é processado neste computador, sem enviar a gravação para a internet.</p>
      </div>
    </header>
    <${AvisosAmbiente} />
    <${ZonaArquivos} />

    ${ativas.length > 0 && html`<section class="secao" aria-labelledby="titulo-andamento">
      <div class="secao-cabecalho"><h2 id="titulo-andamento">Em andamento</h2><a href="#/atividades">Ver atividades</a></div>
      <div class="pilha">${ativas.map((t) => html`<${CartaoTarefa} key=${t.id} tarefa=${t} />`)}</div>
    </section>`}

    <section class="secao" aria-labelledby="titulo-recentes">
      <div class="secao-cabecalho">
        <h2 id="titulo-recentes">Transcrições recentes</h2>
        ${recentes.length > 0 && html`<a href="#/transcricoes">Ver todas</a>`}
      </div>
      ${transcricoes === null ? html`<${Esqueleto} linhas=${3} />`
        : recentes.length === 0 ? html`<div class="cartao"><${Vazio} icone="texto" titulo="Nenhuma transcrição ainda">
            As transcrições concluídas aparecem aqui. Para abrir uma feita antes (pelo .bat ou pela linha de comando), use <a href="#/transcricoes">Transcrições</a> e "Abrir transcrição existente".</${Vazio}></div>`
        : html`<ul class="cartao lista-cartao">${recentes.map((t) => html`<li key=${t.id}><${ItemTranscricao} t=${t} /></li>`)}</ul>`}
    </section>
  </div>`;
}
