import { api } from "../api.js";
import { html, useEffect, useMemo, useState } from "../biblioteca.js";
import { Aviso, Botao, Campo, Carregando, Interruptor, PainelErro, Selecao, descritoPor, notificar, pedirCaminho,
  useAtraso, useTitulo } from "../componentes.js";
import { escolherPasta } from "../desktop.js";
import { bytes, duracao, plural } from "../formato.js";
import { Icone, iconeDoArquivo } from "../icones.js";
import { atualizar, guardarTarefa, ir, obter, useLoja } from "../loja.js";
import { ZonaArquivos } from "./inicio.js";

function formInicial(p) {
  return {
    participantesModo: "nao_sei", participantes: 2, min: 2, max: 6, contexto: "", glossario: "",
    glossarioAlterado: false, saidaModo: "ao_lado", pastaSaida: "", formatos: new Set(p.formatos),
    modelo: p.modelo, modeloOutro: "", modeloRevisao: "", revisao: p.revisao, estilo: p.estilo,
    diarizacao: p.diarizacao, preProcessamento: p.pre_processamento, dispositivo: p.dispositivo,
    precisao: p.precisao, faixaAudio: p.faixa_audio, beam: p.beam, limiar: "", refazer: false,
    manterAudio: false, detalhado: false,
  };
}

const descricaoDe = (lista, valor) => (lista.find((o) => o.valor === valor) || {}).descricao;
const opcoesSelecao = (lista) => lista.map((o) => ({ valor: o.valor, rotulo: o.recomendado ? `${o.rotulo} (recomendado)` : o.rotulo }));

function ArquivoSelecionado({ caminho, estado, erro, aoRemover }) {
  const nome = caminho.split(/[\\/]/).pop();
  const info = estado && estado.info;
  let detalhes;
  if (!estado || estado.carregando) detalhes = "Lendo informações do arquivo...";
  else if (estado.erro) detalhes = estado.erro.mensagem;
  else {
    const faixas = info.faixas_audio.length;
    detalhes = [duracao(info.duracao_s), bytes(info.tamanho_bytes), info.tem_video ? "vídeo" : "áudio",
      faixas > 1 ? `${faixas} faixas de áudio` : null].filter(Boolean).join(" · ");
  }
  const comErro = (estado && estado.erro) || erro;
  return html`<li class=${"arquivo-item" + (comErro ? " com-erro" : "")}>
    <span class="arquivo-icone"><${Icone} nome=${comErro ? "alerta" : iconeDoArquivo(nome)} /></span>
    <span class="corpo">
      <span class="nome" title=${caminho}>${nome}</span>
      <span class="detalhes">${erro || detalhes}</span>
    </span>
    <${Botao} variante="fantasma" tamanho="pequeno" icone="fechar" rotulo=${`Remover ${nome}`} onClick=${aoRemover} />
  </li>`;
}

export function TelaNova() {
  useTitulo("Nova transcrição");
  const catalogo = useLoja((e) => e.opcoes);
  const selecao = useLoja((e) => e.selecao);
  const [infos, setInfos] = useState({});
  const [form, setForm] = useState(null);
  const [termos, setTermos] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState(null);
  const [avancado, setAvancado] = useState(false);

  useEffect(() => { if (catalogo && !form) setForm(formInicial(catalogo.padroes)); }, [catalogo]);
  const alterar = (mudancas) => setForm((f) => ({ ...f, ...mudancas }));

  // Glossário padrão (como o glossario.txt que o transcrever.bat usava automaticamente).
  useEffect(() => {
    if (!form || form.glossarioAlterado) return;
    api.glossario().then((g) => setForm((f) => (f.glossarioAlterado ? f : { ...f, glossario: g.texto }))).catch(() => {});
  }, [!!form]);

  // Quantos termos o backend reconhece no glossário (a interpretação é regra do backend).
  const glossarioAtrasado = useAtraso(form ? form.glossario : "", 350);
  useEffect(() => {
    if (!form) return;
    if (!glossarioAtrasado.trim()) { setTermos(0); return; }
    api.interpretarGlossario({ texto: glossarioAtrasado }).then((r) => setTermos(r.termos.length)).catch(() => setTermos(null));
  }, [glossarioAtrasado]);

  // Informações de cada arquivo escolhido (duração, faixas de áudio).
  useEffect(() => {
    for (const caminho of selecao) {
      if (infos[caminho]) continue;
      setInfos((m) => ({ ...m, [caminho]: { carregando: true } }));
      api.midia(caminho)
        .then((info) => setInfos((m) => ({ ...m, [caminho]: { info } })))
        .catch((e) => setInfos((m) => ({ ...m, [caminho]: { erro: e } })));
    }
  }, [selecao]);

  const remover = (caminho) => atualizar({ selecao: obter().selecao.filter((c) => c !== caminho) });

  const estados = selecao.map((c) => infos[c]);
  const prontos = estados.filter((s) => s && s.info).map((s) => s.info);
  const lendo = estados.some((s) => !s || s.carregando);
  const comErro = estados.some((s) => s && s.erro);
  const multiFaixa = prontos.reduce((melhor, i) => (i.faixas_audio.length > (melhor ? melhor.faixas_audio.length : 1) ? i : melhor), null);
  const totalDuracao = prontos.reduce((s, i) => s + (i.duracao_s || 0), 0);

  const errosArquivo = useMemo(() => {
    const mapa = {};
    for (const c of (erro && erro.campos) || []) {
      const m = /^arquivos\[(\d+)\]/.exec(c.campo);
      if (m && selecao[Number(m[1])]) mapa[selecao[Number(m[1])]] = c.mensagem;
    }
    return mapa;
  }, [erro]);

  if (!catalogo || !form) return html`<div class="conteudo estreito"><${Carregando} /></div>`;
  const c = catalogo;

  async function transcrever() {
    setErro(null);
    setEnviando(true);
    const modelo = form.modelo === "__outro" ? form.modeloOutro.trim() : form.modelo;
    const pedido = {
      arquivos: selecao, contexto: form.contexto || null, glossario_texto: form.glossario || null,
      pasta_saida: form.saidaModo === "pasta" ? form.pastaSaida || null : null, formatos: [...form.formatos],
      modelo, modelo_revisao: form.modeloRevisao || null, revisao: form.revisao, estilo: form.estilo,
      diarizacao: form.diarizacao, pre_processamento: form.preProcessamento, dispositivo: form.dispositivo,
      precisao: form.precisao, faixa_audio: multiFaixa ? form.faixaAudio : "0", beam: Number(form.beam),
      limiar_incerteza: form.limiar === "" ? null : Number(form.limiar), refazer: form.refazer,
      manter_audio: form.manterAudio, detalhado: form.detalhado,
    };
    if (form.participantesModo === "exato") pedido.participantes = Number(form.participantes);
    if (form.participantesModo === "faixa") {
      pedido.min_participantes = Number(form.min);
      pedido.max_participantes = Number(form.max);
    }
    try {
      const r = await api.transcrever(pedido);
      r.tarefas.forEach(guardarTarefa);
      atualizar({ selecao: [] });
      notificar({ tipo: "info", titulo: r.tarefas.length > 1 ? `${r.tarefas.length} transcrições na fila` : "Transcrição iniciada",
        mensagem: "Você pode continuar usando o computador enquanto isso." });
      ir(r.tarefas.length === 1 ? `/atividades/${r.tarefas[0].id}` : "/atividades");
    } catch (e) {
      setErro(e);
      if (["faixa_audio", "modelo", "modelo_revisao", "beam", "limiar_incerteza", "diarizacao", "dispositivo",
        "precisao", "pre_processamento", "estilo"].some((n) => e.campo && e.campo(n))) setAvancado(true);
    } finally {
      setEnviando(false);
    }
  }

  async function escolherDestino() {
    const pasta = await escolherPasta(pedirCaminho);
    if (pasta) alterar({ saidaModo: "pasta", pastaSaida: pasta });
  }

  const erroCampo = (nome) => (erro && erro.campo ? erro.campo(nome) : null);
  const erroParticipantes = erroCampo("participantes") || erroCampo("min_participantes") || erroCampo("max_participantes");
  const lim = c.limites;
  const camposComErroConhecido = ["arquivos", "participantes", "min_participantes", "max_participantes", "pasta_saida",
    "faixa_audio", "modelo", "glossario_texto"];
  const erroGeral = erro && !(erro.campos || []).some((x) => camposComErroConhecido.some((n) => x.campo.startsWith(n)));
  const podeEnviar = selecao.length > 0 && !lendo && !comErro && !enviando &&
    !(form.saidaModo === "pasta" && !form.pastaSaida.trim()) && !(form.modelo === "__outro" && !form.modeloOutro.trim());

  const padraoSaida = prontos[0] ? prontos[0].pasta_saida_padrao : null;

  return html`<div class="conteudo estreito">
    <a class="voltar" href="#/"><${Icone} nome="voltar" tamanho=${16} /> Início</a>
    <header class="cabecalho">
      <div class="titulos">
        <h1>Nova transcrição</h1>
        <p class="subtitulo">Só o arquivo é obrigatório. As outras informações melhoram o resultado.</p>
      </div>
    </header>

    ${selecao.length === 0 ? html`<${ZonaArquivos} aoEscolher=${() => {}} />` : html`<div class="formulario">
      <section class="cartao" aria-labelledby="titulo-arquivos">
        <div class="grupo-form">
          <div class="secao-cabecalho" style="margin:0">
            <h2 id="titulo-arquivos">${selecao.length > 1 ? `${selecao.length} arquivos` : "Arquivo"}</h2>
            ${totalDuracao > 0 && html`<p>${duracao(totalDuracao)} de gravação</p>`}
          </div>
          <ul class="cartao lista-cartao" style="box-shadow:none">
            ${selecao.map((caminho) => html`<${ArquivoSelecionado} key=${caminho} caminho=${caminho} estado=${infos[caminho]}
              erro=${errosArquivo[caminho]} aoRemover=${() => remover(caminho)} />`)}
          </ul>
          <${ZonaArquivos} compacta=${true} aoEscolher=${() => {}} />
        </div>

        <div class="grupo-form">
          <h2>Sobre a reunião</h2>
          <fieldset>
            <legend>Quantas pessoas falam na reunião?</legend>
            <div class="escolhas">
              <label class="escolha"><input type="radio" name="participantes" checked=${form.participantesModo === "nao_sei"}
                onChange=${() => alterar({ participantesModo: "nao_sei" })} />
                <span class="corpo"><span class="titulo">Não sei</span><span class="descricao">O programa descobre sozinho.</span></span></label>
              <label class="escolha"><input type="radio" name="participantes" checked=${form.participantesModo === "exato"}
                onChange=${() => alterar({ participantesModo: "exato" })} />
                <span class="corpo"><span class="titulo">Sei o número exato</span>
                  ${form.participantesModo === "exato" ? html`<span class="linha-campo">
                    <input class="entrada numero" type="number" aria-label="Número de participantes" min=${lim.participantes.minimo}
                      max=${lim.participantes.maximo} value=${form.participantes} onInput=${(e) => alterar({ participantes: e.currentTarget.value })} />
                    <span class="descricao">pessoas</span></span>`
                    : html`<span class="descricao">Ajuda a separar vozes parecidas.</span>`}</span></label>
              <label class="escolha"><input type="radio" name="participantes" checked=${form.participantesModo === "faixa"}
                onChange=${() => alterar({ participantesModo: "faixa" })} />
                <span class="corpo"><span class="titulo">Sei mais ou menos</span>
                  ${form.participantesModo === "faixa" ? html`<span class="linha-campo"><span class="descricao">Entre</span>
                    <input class="entrada numero" type="number" aria-label="Mínimo de participantes" min="1" value=${form.min}
                      onInput=${(e) => alterar({ min: e.currentTarget.value })} />
                    <span class="descricao">e</span>
                    <input class="entrada numero" type="number" aria-label="Máximo de participantes" min="1" value=${form.max}
                      onInput=${(e) => alterar({ max: e.currentTarget.value })} />
                    <span class="descricao">pessoas</span></span>`
                    : html`<span class="descricao">Informe um mínimo e um máximo.</span>`}</span></label>
            </div>
            ${erroParticipantes && html`<p class="erro-campo" role="alert" style="margin-top:8px"><${Icone} nome="alerta" />${erroParticipantes}</p>`}
          </fieldset>

          <${Campo} id="contexto" rotulo="Assunto da reunião" opcional=${true} erro=${erroCampo("contexto")}
            ajuda="Organização, projeto ou tema. Ajuda a reconhecer o vocabulário; não aparece no texto.">
            <input id="contexto" class="entrada" value=${form.contexto} maxlength="2000"
              placeholder="Ex.: Reunião do conselho sobre o orçamento 2027" aria-describedby=${descritoPor("contexto", erroCampo("contexto"), true)}
              onInput=${(e) => alterar({ contexto: e.currentTarget.value })} />
          </${Campo}>

          <${Campo} id="glossario" rotulo="Glossário" opcional=${true} erro=${erroCampo("glossario_texto")}
            ajuda=${html`Nomes de pessoas, siglas e termos técnicos citados: um por linha, ou vários separados por ponto e vírgula.
              ${termos ? ` ${plural(termos, "termo reconhecido", "termos reconhecidos")}.` : ""} O glossário padrão é editado em <a href="#/configuracoes/glossario">Configurações</a>.`}>
            <textarea id="glossario" class="entrada" rows="4" value=${form.glossario} placeholder="Ex.: Mariana; Roberto; SIGEP"
              aria-describedby=${descritoPor("glossario", erroCampo("glossario_texto"), true)}
              onInput=${(e) => alterar({ glossario: e.currentTarget.value, glossarioAlterado: true })}></textarea>
          </${Campo}>
        </div>

        <div class="grupo-form">
          <h2>Resultado</h2>
          <fieldset>
            <legend>Onde salvar os arquivos</legend>
            <div class="escolhas">
              <label class="escolha"><input type="radio" name="saida" checked=${form.saidaModo === "ao_lado"}
                onChange=${() => alterar({ saidaModo: "ao_lado" })} />
                <span class="corpo"><span class="titulo">Ao lado da gravação</span>
                  <span class="descricao">${padraoSaida ? html`Numa pasta nova: <span class="mono">${padraoSaida}</span>`
                    : "Numa pasta nova chamada <nome do arquivo>_transcricao."}</span></span></label>
              <label class="escolha"><input type="radio" name="saida" checked=${form.saidaModo === "pasta"}
                onChange=${() => alterar({ saidaModo: "pasta" })} />
                <span class="corpo"><span class="titulo">Em outra pasta</span>
                  <span class="descricao">Cada gravação ganha uma subpasta com o nome dela.</span>
                  ${form.saidaModo === "pasta" && html`<span class="com-botao" style="margin-top:8px">
                    <input class="entrada" aria-label="Pasta de destino" value=${form.pastaSaida} placeholder="C:\\Transcricoes"
                      aria-invalid=${erroCampo("pasta_saida") ? "true" : undefined}
                      onInput=${(e) => alterar({ pastaSaida: e.currentTarget.value })} />
                    <${Botao} icone="pasta" onClick=${escolherDestino}>Escolher</${Botao}></span>`}
                </span></label>
            </div>
            ${erroCampo("pasta_saida") && html`<p class="erro-campo" role="alert" style="margin-top:8px"><${Icone} nome="alerta" />${erroCampo("pasta_saida")}</p>`}
          </fieldset>

          <fieldset>
            <legend>Formatos</legend>
            <div class="caixas">
              ${c.formatos.map((f) => {
                const sempre = f.valor === "json";
                return html`<label class="caixa" title=${f.descricao}>
                  <input type="checkbox" checked=${sempre || form.formatos.has(f.valor)} disabled=${sempre}
                    onChange=${(e) => { const s = new Set(form.formatos); e.currentTarget.checked ? s.add(f.valor) : s.delete(f.valor); alterar({ formatos: s }); }} />
                  <span>${f.rotulo}${sempre && html`<span class="descricao">Sempre gerado</span>`}</span>
                </label>`;
              })}
            </div>
            <p class="ajuda" style="margin-top:10px">O relatório de conferência (pontos para ouvir de novo) é sempre gerado.</p>
          </fieldset>
        </div>

        <details class="avancado" open=${avancado} onToggle=${(e) => setAvancado(e.currentTarget.open)}>
          <summary><${Icone} nome="direita" />Opções avançadas<span class="ajuda">Modelo, identificação de participantes, áudio e mais</span></summary>
          <div class="grupo-form" style="border-top:0;padding-top:4px">
            ${multiFaixa && html`<${Campo} id="faixa" rotulo="Faixa de áudio" erro=${erroCampo("faixa_audio")}
              ajuda="O arquivo tem mais de uma faixa (gravações do OBS, por exemplo). Escolha a que tem a conversa completa ou misture todas.">
              <${Selecao} id="faixa" valor=${form.faixaAudio} aoMudar=${(v) => alterar({ faixaAudio: v })} descrita="faixa-ajuda"
                opcoes=${[...multiFaixa.faixas_audio.map((f) => ({ valor: String(f.indice),
                  rotulo: [`Faixa ${f.indice + 1}`, f.titulo, f.idioma && f.idioma !== "und" ? f.idioma : null, f.codec,
                    f.canais === 1 ? "mono" : f.canais === 2 ? "estéreo" : `${f.canais} canais`].filter(Boolean).join(" · ") })),
                  { valor: "todas", rotulo: "Misturar todas as faixas" }]} />
            </${Campo}>`}
            <div class="grade-campos">
              <${Campo} id="modelo" rotulo="Modelo de reconhecimento" erro=${erroCampo("modelo")}
                ajuda=${form.modelo === "__outro" ? "Nome aceito pelo faster-whisper ou caminho de um modelo local." : descricaoDe(c.modelos, form.modelo)}>
                <${Selecao} id="modelo" valor=${form.modelo} aoMudar=${(v) => alterar({ modelo: v })} descrita="modelo-ajuda"
                  opcoes=${[...opcoesSelecao(c.modelos), { valor: "__outro", rotulo: "Outro modelo..." }]} />
                ${form.modelo === "__outro" && html`<input class="entrada" aria-label="Nome do modelo" value=${form.modeloOutro}
                  placeholder="Ex.: medium" onInput=${(e) => alterar({ modeloOutro: e.currentTarget.value })} />`}
              </${Campo}>
              <${Campo} id="diarizacao" rotulo="Identificação de participantes" ajuda=${descricaoDe(c.diarizacao, form.diarizacao)}>
                <${Selecao} id="diarizacao" valor=${form.diarizacao} aoMudar=${(v) => alterar({ diarizacao: v })}
                  descrita="diarizacao-ajuda" opcoes=${opcoesSelecao(c.diarizacao)} />
              </${Campo}>
              <${Campo} id="estilo" rotulo="Estilo do texto" ajuda=${descricaoDe(c.estilos, form.estilo)}>
                <${Selecao} id="estilo" valor=${form.estilo} aoMudar=${(v) => alterar({ estilo: v })} descrita="estilo-ajuda"
                  opcoes=${opcoesSelecao(c.estilos)} />
              </${Campo}>
              <${Campo} id="pre" rotulo="Tratamento do áudio" ajuda=${descricaoDe(c.pre_processamento, form.preProcessamento)}>
                <${Selecao} id="pre" valor=${form.preProcessamento} aoMudar=${(v) => alterar({ preProcessamento: v })}
                  descrita="pre-ajuda" opcoes=${opcoesSelecao(c.pre_processamento)} />
              </${Campo}>
              <${Campo} id="dispositivo" rotulo="Processar com" ajuda=${descricaoDe(c.dispositivos, form.dispositivo)}>
                <${Selecao} id="dispositivo" valor=${form.dispositivo} aoMudar=${(v) => alterar({ dispositivo: v })}
                  descrita="dispositivo-ajuda" opcoes=${opcoesSelecao(c.dispositivos)} />
              </${Campo}>
              <${Campo} id="precisao" rotulo="Precisão numérica" ajuda=${descricaoDe(c.precisoes, form.precisao)}>
                <${Selecao} id="precisao" valor=${form.precisao} aoMudar=${(v) => alterar({ precisao: v })}
                  descrita="precisao-ajuda" opcoes=${opcoesSelecao(c.precisoes)} />
              </${Campo}>
              <${Campo} id="modelo-revisao" rotulo="Modelo da revisão" erro=${erroCampo("modelo_revisao")}
                ajuda="Um modelo diferente no segundo passo dá uma segunda opinião nos trechos duvidosos.">
                <${Selecao} id="modelo-revisao" valor=${form.modeloRevisao} aoMudar=${(v) => alterar({ modeloRevisao: v })}
                  descrita="modelo-revisao-ajuda" opcoes=${[{ valor: "", rotulo: "Igual ao modelo de reconhecimento" },
                    ...c.modelos.map((m) => ({ valor: m.valor, rotulo: m.rotulo }))]} />
              </${Campo}>
              <div class="grade-campos" style="gap:16px">
                <${Campo} id="beam" rotulo="Largura do feixe" erro=${erroCampo("beam")} ajuda=${`Padrão: ${lim.beam.padrao}.`}>
                  <input id="beam" class="entrada" type="number" min=${lim.beam.minimo} max=${lim.beam.maximo} value=${form.beam}
                    aria-describedby="beam-ajuda" onInput=${(e) => alterar({ beam: e.currentTarget.value })} />
                </${Campo}>
                <${Campo} id="limiar" rotulo="Limiar de incerteza" erro=${erroCampo("limiar_incerteza")}
                  ajuda=${`Padrão: ${String(lim.limiar_incerteza.padrao).replace(".", ",")}.`}>
                  <input id="limiar" class="entrada" type="number" step=${lim.limiar_incerteza.passo} min=${lim.limiar_incerteza.minimo}
                    max=${lim.limiar_incerteza.maximo} value=${form.limiar} placeholder=${String(lim.limiar_incerteza.padrao).replace(".", ",")}
                    aria-describedby="limiar-ajuda" onInput=${(e) => alterar({ limiar: e.currentTarget.value })} />
                </${Campo}>
              </div>
            </div>
            <div class="pilha" style="gap:16px;margin-top:6px">
              <${Interruptor} titulo="Revisão em segundo passo (recomendado)" marcado=${form.revisao} aoMudar=${(v) => alterar({ revisao: v })}
                descricao="Cada trecho duvidoso é decodificado mais duas vezes e as versões são comparadas palavra a palavra. Desligar deixa mais rápido e menos preciso." />
              <${Interruptor} titulo="Refazer todas as etapas" marcado=${form.refazer} aoMudar=${(v) => alterar({ refazer: v })}
                descricao="Ignora resultados de uma transcrição anterior do mesmo arquivo (normalmente eles são reaproveitados)." />
              <${Interruptor} titulo="Manter os áudios intermediários" marcado=${form.manterAudio} aoMudar=${(v) => alterar({ manterAudio: v })}
                descricao="Guarda os arquivos WAV tratados na pasta .trabalho, para análise." />
              <${Interruptor} titulo="Registro técnico detalhado" marcado=${form.detalhado} aoMudar=${(v) => alterar({ detalhado: v })}
                descricao="Mais mensagens no registro (log), úteis para diagnosticar problemas." />
            </div>
          </div>
        </details>
      </section>

      ${erroGeral && html`<${PainelErro} erro=${erro} />`}
      ${erro && !erroGeral && html`<${Aviso} tipo="erro" titulo="Corrija os pontos indicados">
        <p>${erro.mensagem}</p>${erro.dica && html`<p class="dica"><b>Como resolver:</b> ${erro.dica}</p>`}</${Aviso}>`}

      <div class="rodape-acao">
        <span class="resumo">${lendo ? "Lendo os arquivos..." : comErro ? "Remova os arquivos com problema para continuar."
          : html`<strong>${plural(selecao.length, "arquivo", "arquivos")}</strong>${totalDuracao ? ` · ${duracao(totalDuracao)} de gravação` : ""}`}</span>
        <${Botao} variante="primario" tamanho="grande" icone="ok" carregando=${enviando} disabled=${!podeEnviar} onClick=${transcrever}>
          ${selecao.length > 1 ? `Transcrever ${selecao.length} arquivos` : "Transcrever"}
        </${Botao}>
      </div>
    </div>`}
  </div>`;
}
