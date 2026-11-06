import { api } from "../api.js";
import { html, useEffect, useState } from "../biblioteca.js";
import { Botao, Esqueleto, PainelErro, Vazio, notificar, pedirCaminho, useAtraso, useTitulo } from "../componentes.js";
import { escolherTranscricao } from "../desktop.js";
import { Icone } from "../icones.js";
import { atualizar, ir, useLoja } from "../loja.js";
import { ItemTranscricao } from "../pecas.js";

export async function recarregarTranscricoes() {
  try {
    const r = await api.transcricoes();
    atualizar({ transcricoes: r.itens });
  } catch (e) { /* a lista continua como estava; a conexão é sinalizada pela faixa de conexão */ }
}

export async function abrirExistente() {
  const caminho = await escolherTranscricao(pedirCaminho);
  if (!caminho) return;
  try {
    const t = await api.importar(caminho);
    recarregarTranscricoes();
    notificar({ titulo: "Transcrição aberta", mensagem: t.nome });
    ir(`/transcricoes/${t.id}`);
  } catch (e) {
    notificar({ tipo: "erro", titulo: e.mensagem, mensagem: e.dica, duracao: 9000 });
  }
}

export function TelaTranscricoes() {
  useTitulo("Transcrições");
  const todas = useLoja((e) => e.transcricoes);
  const [busca, setBusca] = useState("");
  const termo = useAtraso(busca.trim(), 250);
  const [filtradas, setFiltradas] = useState(null);
  const [erro, setErro] = useState(null);

  // A busca é feita pela API (por nome do arquivo e de participantes).
  useEffect(() => {
    if (!termo) { setFiltradas(null); return; }
    let vivo = true;
    api.transcricoes(termo).then((r) => vivo && setFiltradas(r.itens)).catch((e) => vivo && setErro(e));
    return () => { vivo = false; };
  }, [termo, todas]);

  const itens = termo ? filtradas : todas;
  return html`<div class="conteudo">
    <header class="cabecalho">
      <div class="titulos">
        <h1>Transcrições</h1>
        <p class="subtitulo">Todas as transcrições concluídas e as abertas a partir de um arquivo .json.</p>
      </div>
      <div class="acoes">
        <${Botao} icone="pasta" onClick=${abrirExistente}>Abrir transcrição existente</${Botao}>
        <a class="botao primario" href="#/nova"><${Icone} nome="mais" />Nova transcrição</a>
      </div>
    </header>

    ${todas && todas.length > 0 && html`<div class="busca" style="margin-bottom:16px;max-width:420px">
      <${Icone} nome="busca" />
      <input class="entrada" type="search" placeholder="Buscar por arquivo ou participante" aria-label="Buscar transcrições"
        value=${busca} onInput=${(e) => setBusca(e.currentTarget.value)} />
    </div>`}
    <${PainelErro} erro=${erro} />

    ${itens === null ? html`<${Esqueleto} linhas=${4} />`
      : itens.length === 0 ? html`<div class="cartao">${termo
          ? html`<${Vazio} icone="busca" titulo="Nada encontrado">Nenhuma transcrição corresponde a "${termo}".</${Vazio}>`
          : html`<${Vazio} icone="texto" titulo="Nenhuma transcrição ainda" acoes=${html`
              <a class="botao primario" href="#/nova">Transcrever uma gravação</a>
              <${Botao} onClick=${abrirExistente}>Abrir transcrição existente</${Botao}>`}>
              Transcrições feitas antes, pelo transcrever.bat ou pela linha de comando, podem ser abertas pelo arquivo .json
              que fica na pasta delas.</${Vazio}>`}</div>`
      : html`<ul class="cartao lista-cartao">${itens.map((t) => html`<li key=${t.id}><${ItemTranscricao} t=${t} /></li>`)}</ul>`}
  </div>`;
}
