import { api } from "../api.js";
import { html, useEffect, useRef, useState } from "../biblioteca.js";
import { Aviso, Barra, Botao, Carregando, PainelErro, Vazio, confirmar, executar, notificar, useTitulo } from "../componentes.js";
import { dataHora, duracao, quando, restante } from "../formato.js";
import { Icone, iconeDoArquivo } from "../icones.js";
import { ativa, esquecerTarefa, guardarTarefa, ir, ouvirLog, useLoja } from "../loja.js";
import { CartaoTarefa, EtiquetaEstado, NOMES_TIPO, cancelarTarefa, repetirTarefa, situacaoTarefa } from "../pecas.js";

export function TelaAtividades() {
  useTitulo("Atividades");
  const tarefas = useLoja((e) => e.tarefas);
  const todas = [...tarefas.values()].sort((a, b) => b.criada_em.localeCompare(a.criada_em));
  const andamento = todas.filter((t) => t.estado === "em_andamento");
  const fila = todas.filter((t) => t.estado === "na_fila").sort((a, b) => (a.posicao_fila || 0) - (b.posicao_fila || 0));
  const anteriores = todas.filter((t) => !ativa(t));

  return html`<div class="conteudo">
    <header class="cabecalho">
      <div class="titulos">
        <h1>Atividades</h1>
        <p class="subtitulo">Transcrições e outras tarefas, com o andamento de cada uma. As transcrições rodam uma de cada vez.</p>
      </div>
      <div class="acoes"><a class="botao primario" href="#/nova"><${Icone} nome="mais" />Nova transcrição</a></div>
    </header>

    ${todas.length === 0 && html`<div class="cartao"><${Vazio} icone="atividade" titulo="Nenhuma atividade"
      acoes=${html`<a class="botao" href="#/nova">Transcrever uma gravação</a>`}>
      Quando você iniciar uma transcrição, o andamento aparece aqui.</${Vazio}></div>`}

    ${andamento.length > 0 && html`<section class="secao" style="margin-top:0" aria-labelledby="t-andamento">
      <div class="secao-cabecalho"><h2 id="t-andamento">Em andamento</h2></div>
      <div class="pilha">${andamento.map((t) => html`<${CartaoTarefa} key=${t.id} tarefa=${t} />`)}</div>
    </section>`}

    ${fila.length > 0 && html`<section class="secao" aria-labelledby="t-fila">
      <div class="secao-cabecalho"><h2 id="t-fila">Na fila</h2><p>${fila.length === 1 ? "Começa quando a atual terminar." : "Começam na ordem abaixo."}</p></div>
      <div class="pilha">${fila.map((t) => html`<${CartaoTarefa} key=${t.id} tarefa=${t} compacto=${true} />`)}</div>
    </section>`}

    ${anteriores.length > 0 && html`<section class="secao" aria-labelledby="t-anteriores">
      <div class="secao-cabecalho"><h2 id="t-anteriores">Anteriores</h2></div>
      <ul class="cartao lista-cartao">
        ${anteriores.map((t) => html`<li key=${t.id}><a class="item-lista" href=${`#/atividades/${t.id}`}>
          <span class="arquivo-icone"><${Icone} nome=${t.tipo === "transcricao" ? iconeDoArquivo(t.titulo) : "ajustes"} /></span>
          <span class="corpo">
            <span class="nome">${t.titulo}</span>
            <span class="detalhes">${NOMES_TIPO[t.tipo] !== t.titulo && html`<span>${NOMES_TIPO[t.tipo]}</span>`}<span>${quando(t.criada_em)}</span>
              ${t.estado === "falhou" && t.erro ? html`<span>${t.erro.mensagem}</span>` : null}</span>
          </span>
          <span class="lado"><${EtiquetaEstado} estado=${t.estado} /></span>
          <${Icone} nome="direita" />
        </a></li>`)}
      </ul>
    </section>`}
  </div>`;
}

function Etapa({ etapa: e, fracao, atual }) {
  const marcador = { concluida: html`<${Icone} nome="ok" />`, reaproveitada: html`<${Icone} nome="ok" />`,
    falhou: html`<${Icone} nome="fechar" />`, em_andamento: html`<span class="giro"></span>`,
    interrompida: html`<${Icone} nome="parar" />` }[e.estado] || e.numero;
  const lado = e.estado === "reaproveitada" ? "reaproveitada" : e.estado === "ignorada" ? "não se aplica"
    : e.estado === "em_andamento" && fracao !== null && fracao !== undefined ? `${Math.round(fracao * 100)}%`
    : e.duracao_s !== null && e.duracao_s !== undefined && e.estado !== "pendente" ? duracao(e.duracao_s) : "";
  const nomeEstado = { pendente: "pendente", em_andamento: "em andamento", concluida: "concluída", reaproveitada: "reaproveitada",
    ignorada: "não se aplica", falhou: "falhou", interrompida: "interrompida" }[e.estado];
  return html`<li class=${"etapa " + e.estado} aria-current=${atual ? "step" : undefined}>
    <span class="marcador" aria-hidden="true">${marcador}</span>
    <span class="textos">
      <span class="titulo">${e.titulo}<span class="visualmente-oculto">: ${nomeEstado}</span></span>
      ${(e.estado === "em_andamento" || e.estado === "falhou") && e.detalhe && html`<span class="detalhe">${e.detalhe}</span>`}
      ${e.estado === "em_andamento" && html`<${Barra} valor=${(fracao || 0) * 100} indeterminada=${fracao === null || fracao === undefined}
        rotulo=${`Progresso de ${e.titulo}`} />`}
    </span>
    <span class="lado">${lado}</span>
  </li>`;
}

function Registro({ tarefa }) {
  const [linhas, setLinhas] = useState(null);
  const proxima = useRef(0);
  const caixa = useRef(null);
  const [aberto, setAberto] = useState(false);

  useEffect(() => {
    if (!aberto) return undefined;
    let vivo = true;
    api.registro(tarefa.id).then((r) => { if (vivo) { setLinhas(r.linhas); proxima.current = r.proxima; } })
      .catch(() => vivo && setLinhas([]));
    const parar = ouvirLog((d) => {
      if (d.tarefa_id !== tarefa.id || d.numero < proxima.current) return;
      proxima.current = d.numero + 1;
      setLinhas((ls) => [...(ls || []), d.linha]);
    });
    return () => { vivo = false; parar(); };
  }, [aberto, tarefa.id]);

  useEffect(() => {
    const c = caixa.current;
    if (c && c.scrollHeight - c.scrollTop - c.clientHeight < 80) c.scrollTop = c.scrollHeight;
  }, [linhas]);

  return html`<details class="cartao" style="margin-top:22px" onToggle=${(e) => setAberto(e.currentTarget.open)}>
    <summary class="item-lista" style="cursor:pointer;list-style:none">
      <span class="arquivo-icone"><${Icone} nome="codigo" /></span>
      <span class="corpo"><span class="nome">Detalhes técnicos</span><span class="detalhes">Registro (log) do processamento, para diagnóstico</span></span>
      <${Icone} nome="baixo" />
    </summary>
    <div class="cartao-corpo" style="padding-top:0">
      ${linhas === null ? html`<${Carregando} texto="Carregando o registro..." />`
        : html`<pre class="registro" ref=${caixa} tabindex="0" aria-label="Registro técnico">${linhas.join("\n") || "Sem mensagens ainda."}</pre>
          <div class="acoes" style="margin-top:10px">
            <${Botao} tamanho="pequeno" icone="copiar" onClick=${async () => {
              try { await navigator.clipboard.writeText(linhas.join("\n")); notificar({ titulo: "Registro copiado" }); }
              catch (e) { notificar({ tipo: "erro", titulo: "Não foi possível copiar" }); }
            }}>Copiar</${Botao}>
          </div>`}
    </div>
  </details>`;
}

export function TelaTarefa({ id }) {
  const tarefas = useLoja((e) => e.tarefas);
  const [erro, setErro] = useState(null);
  const t = tarefas.get(id);
  const [agora, setAgora] = useState(Date.now());
  useTitulo(t ? t.titulo : "Atividade");

  useEffect(() => {
    if (t) return;
    api.tarefa(id).then(guardarTarefa).catch(setErro);
  }, [id, !!t]);

  // Tempo decorrido ao vivo enquanto a tarefa roda (os eventos chegam em intervalos irregulares).
  useEffect(() => {
    if (!t || t.estado !== "em_andamento") return undefined;
    const intervalo = setInterval(() => setAgora(Date.now()), 1000);
    return () => clearInterval(intervalo);
  }, [t && t.estado]);

  if (!t) {
    return html`<div class="conteudo estreito">
      <a class="voltar" href="#/atividades"><${Icone} nome="voltar" tamanho=${16} /> Atividades</a>
      ${erro ? html`<${PainelErro} erro=${erro} />` : html`<${Carregando} />`}
    </div>`;
  }

  const p = t.progresso || {};
  const andamento = t.estado === "em_andamento";
  const eta = restante(p.restante_estimado_s);
  const resultado = t.resultado;
  const decorrido = andamento && t.iniciada_em ? Math.max(0, (agora - new Date(t.iniciada_em).getTime()) / 1000) : p.decorrido_s;

  async function remover() {
    const ok = await confirmar({ titulo: "Remover esta atividade?", mensagem: "Ela sai da lista de atividades. Transcrições e arquivos não são apagados.",
      confirmar: "Remover", perigo: true });
    if (!ok) return;
    const r = await executar(() => api.removerTarefa(t.id), "Não foi possível remover");
    if (r !== undefined) { esquecerTarefa(t.id); ir("/atividades"); }
  }

  async function cancelar() {
    const ok = t.estado === "na_fila" || await confirmar({ titulo: "Cancelar a transcrição?",
      mensagem: "O processamento é interrompido agora. As etapas já concluídas ficam guardadas e serão reaproveitadas se você transcrever este arquivo de novo.",
      confirmar: "Cancelar transcrição", cancelar: "Continuar", perigo: true });
    if (ok) cancelarTarefa(t);
  }

  return html`<div class="conteudo estreito">
    <a class="voltar" href="#/atividades"><${Icone} nome="voltar" tamanho=${16} /> Atividades</a>
    <header class="cabecalho">
      <div class="titulos">
        <h1>${t.titulo}</h1>
        <div class="meta">
          <${EtiquetaEstado} estado=${t.estado} />
          <span>${NOMES_TIPO[t.tipo]}</span>
          <span><${Icone} nome="relogio" tamanho=${15} />${t.iniciada_em ? `Iniciada em ${dataHora(t.iniciada_em)}` : `Criada em ${dataHora(t.criada_em)}`}</span>
          ${decorrido ? html`<span>${andamento ? "Rodando há" : "Durou"} ${duracao(decorrido)}</span>` : null}
        </div>
      </div>
      <div class="acoes">
        ${t.pode_cancelar && html`<${Botao} variante="perigo" icone="fechar" onClick=${cancelar}>Cancelar</${Botao}>`}
        ${t.pode_repetir && t.estado !== "concluida" && html`<${Botao} variante="primario" icone="repetir" onClick=${() => repetirTarefa(t)}>
          ${t.tipo === "transcricao" ? "Retomar" : "Tentar de novo"}</${Botao}>`}
        ${!ativa(t) && html`<${Botao} variante="fantasma" icone="lixeira" rotulo="Remover da lista" onClick=${remover} />`}
      </div>
    </header>

    ${t.estado === "concluida" && t.tipo === "transcricao" && resultado && html`<${Aviso} tipo="sucesso" titulo="Transcrição concluída"
      acoes=${html`<div class="acoes">
        ${resultado.transcricao_id && html`<a class="botao primario" href=${`#/transcricoes/${resultado.transcricao_id}`}><${Icone} nome="texto" />Abrir transcrição</a>`}
        <${Botao} icone="pasta" onClick=${() => executar(() => api.abrir(resultado.pasta), "Não foi possível abrir a pasta")}>Abrir pasta</${Botao}>
        <${Botao} variante="fantasma" icone="repetir" onClick=${() => repetirTarefa(t)}>Transcrever de novo</${Botao}>
      </div>`}>
      <p>Os arquivos estão em <span class="mono">${resultado.pasta}</span>.</p>
    </${Aviso}>`}
    ${t.estado === "concluida" && t.tipo !== "transcricao" && html`<${Aviso} tipo="sucesso" titulo="Concluída"
      acoes=${html`<a class="botao" href="#/configuracoes">Ver o ambiente</a>`}>
      ${resultado && resultado.mensagens ? html`<p>${resultado.mensagens.join(" ")}</p>` : html`<p>O ambiente foi verificado.</p>`}
    </${Aviso}>`}
    ${t.estado === "falhou" && t.erro && html`<${Aviso} tipo="erro" titulo=${t.erro.mensagem}>
      ${t.erro.dica && html`<p class="dica"><b>Como resolver:</b> ${t.erro.dica}</p>`}
      ${t.tipo === "transcricao" && html`<p>As etapas concluídas foram guardadas: ao tentar de novo, o processamento continua de onde parou.</p>`}
    </${Aviso}>`}
    ${t.estado === "interrompida" && html`<${Aviso} tipo="atencao" titulo="Tarefa interrompida">
      <p>${t.erro ? t.erro.mensagem : "A tarefa não chegou ao fim."} ${t.erro && t.erro.dica ? t.erro.dica : ""}</p>
    </${Aviso}>`}
    ${t.estado === "cancelada" && html`<${Aviso} tipo="info" titulo="Tarefa cancelada">
      <p>${t.tipo === "transcricao" ? "As etapas já concluídas ficam guardadas e serão reaproveitadas ao retomar." : "Nada foi alterado."}</p>
    </${Aviso}>`}

    <section class="cartao cartao-corpo" style="margin-top:20px" aria-labelledby="t-progresso">
      <h2 id="t-progresso" class="visualmente-oculto">Progresso</h2>
      ${t.estado === "na_fila" ? html`<p class="texto-2" role="status">${situacaoTarefa(t)}</p>` : html`
        <div class="pilha" style="gap:8px">
          <div class="numeros" role="status" aria-live="polite">
            <span><strong>${Math.round(p.percentual || 0)}%</strong>${andamento && p.mensagem ? ` · ${p.mensagem}` : ""}</span>
            <span>${andamento ? (eta ? `${eta} restantes` : "calculando o tempo restante...") : ""}</span>
          </div>
          <${Barra} grossa=${true} valor=${p.percentual} estado=${t.estado === "concluida" ? "sucesso" : t.estado === "falhou" ? "erro" : ""}
            indeterminada=${andamento && p.percentual < 1} rotulo="Progresso geral" />
        </div>`}
      ${(p.etapas || []).length > 1 && html`<ol class="etapas" style="margin-top:18px" aria-label="Etapas">
        ${p.etapas.map((e) => html`<${Etapa} key=${e.chave} etapa=${e} fracao=${e.numero === p.etapa_atual ? p.fracao_etapa : null}
          atual=${e.numero === p.etapa_atual} />`)}
      </ol>`}
    </section>

    <${Registro} tarefa=${t} />
  </div>`;
}
