// Cliente da API REST do Transcritor. A interface não executa nenhuma regra de negócio:
// tudo passa por aqui. Erros chegam sempre como ErroApi, com mensagem e dica para a pessoa usuária.

const BASE = "/api/v1";

export class ErroApi extends Error {
  constructor({ status = 0, codigo = "erro", mensagem = "Erro inesperado.", dica = null, campos = [] } = {}) {
    super(mensagem);
    this.status = status;
    this.codigo = codigo;
    this.mensagem = mensagem;
    this.dica = dica;
    this.campos = campos;
  }

  campo(nome) {
    const c = this.campos.find((x) => x.campo === nome || x.campo.startsWith(nome + "["));
    return c ? c.mensagem : null;
  }
}

const SEM_SERVICO = {
  status: 0,
  codigo: "servico_indisponivel",
  mensagem: "Não foi possível falar com o serviço do Transcritor.",
  dica: "Aguarde alguns segundos. Se o problema continuar, feche e abra o aplicativo de novo.",
};

async function requisitar(metodo, caminho, corpo) {
  let resposta;
  try {
    resposta = await fetch(BASE + caminho, {
      method: metodo,
      headers: corpo === undefined ? {} : { "Content-Type": "application/json" },
      body: corpo === undefined ? undefined : JSON.stringify(corpo),
    });
  } catch (e) {
    throw new ErroApi(SEM_SERVICO);
  }
  if (resposta.status === 204 || resposta.status === 202 && resposta.headers.get("content-length") === "0") return null;
  const tipo = resposta.headers.get("content-type") || "";
  const dados = tipo.includes("json") ? await resposta.json().catch(() => null) : await resposta.text();
  if (!resposta.ok) {
    const e = (dados && dados.erro) || {};
    throw new ErroApi({
      status: resposta.status, codigo: e.codigo || "erro_http",
      mensagem: e.mensagem || `O serviço respondeu com o erro ${resposta.status}.`, dica: e.dica || null,
      campos: e.campos || [],
    });
  }
  return dados;
}

const get = (c) => requisitar("GET", c);
const post = (c, corpo) => requisitar("POST", c, corpo === undefined ? {} : corpo);
const qs = (params) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v === undefined || v === null || v === "") continue;
    for (const item of Array.isArray(v) ? v : [v]) p.append(k, item);
  }
  const s = p.toString();
  return s ? "?" + s : "";
};

export const api = {
  saude: () => get("/saude"),
  sistema: () => get("/sistema"),
  opcoes: () => get("/opcoes"),
  abrir: (caminho, revelar = false) => post("/sistema/abrir", { caminho, revelar }),

  ambiente: () => get("/ambiente"),
  verificarAmbiente: () => post("/ambiente/verificacoes"),
  baixarModelos: () => post("/ambiente/modelos/downloads"),

  tarefas: (params) => get("/tarefas" + qs(params)),
  tarefa: (id) => get(`/tarefas/${id}`),
  cancelar: (id) => post(`/tarefas/${id}/cancelar`),
  repetir: (id) => post(`/tarefas/${id}/repetir`),
  removerTarefa: (id) => requisitar("DELETE", `/tarefas/${id}`),
  registro: (id, desde = 0) => get(`/tarefas/${id}/registro${qs({ desde })}`),

  transcrever: (pedido) => post("/transcricoes", pedido),
  transcricoes: (busca) => get("/transcricoes" + qs({ busca })),
  importar: (caminho) => post("/transcricoes/importacoes", { caminho }),
  transcricao: (id) => get(`/transcricoes/${id}`),
  removerTranscricao: (id) => requisitar("DELETE", `/transcricoes/${id}`),
  conteudo: (id) => get(`/transcricoes/${id}/conteudo`),
  relatorio: (id) => get(`/transcricoes/${id}/relatorio`),
  participantes: (id) => get(`/transcricoes/${id}/participantes`),
  nomear: (id, pedido) => requisitar("PATCH", `/transcricoes/${id}/participantes`, pedido),
  exportar: (id, pedido) => post(`/transcricoes/${id}/exportacoes`, pedido),
  urlMidia: (id) => `${BASE}/transcricoes/${id}/midia`,

  midia: (caminho, pasta_saida) => get("/midia/informacoes" + qs({ caminho, pasta_saida })),

  token: () => get("/configuracao/token-hf"),
  salvarToken: (token) => requisitar("PUT", "/configuracao/token-hf", { token }),
  removerToken: () => requisitar("DELETE", "/configuracao/token-hf"),
  glossario: () => get("/configuracao/glossario"),
  salvarGlossario: (texto) => requisitar("PUT", "/configuracao/glossario", { texto }),
  interpretarGlossario: (pedido) => post("/configuracao/glossario/interpretar", pedido),

  // Envio de arquivo com progresso (usado quando a interface roda num navegador comum).
  enviar(arquivo, aoProgresso) {
    return new Promise((resolver, rejeitar) => {
      const xhr = new XMLHttpRequest();
      const dados = new FormData();
      dados.append("arquivo", arquivo, arquivo.name);
      xhr.open("POST", BASE + "/midia/envios");
      xhr.upload.onprogress = (e) => e.lengthComputable && aoProgresso && aoProgresso(e.loaded / e.total);
      xhr.onerror = () => rejeitar(new ErroApi(SEM_SERVICO));
      xhr.onload = () => {
        let corpo = null;
        try { corpo = JSON.parse(xhr.responseText); } catch (e) { /* sem corpo */ }
        if (xhr.status >= 200 && xhr.status < 300) resolver(corpo);
        else rejeitar(new ErroApi({ status: xhr.status, ...(corpo && corpo.erro ? corpo.erro : {}) }));
      };
      xhr.send(dados);
    });
  },
};

// Eventos em tempo real (Server-Sent Events). O navegador reconecta sozinho.
export function conectarEventos(manipuladores) {
  const fonte = new EventSource(BASE + "/eventos");
  for (const [tipo, funcao] of Object.entries(manipuladores)) {
    if (tipo === "aberto" || tipo === "erro") continue;
    fonte.addEventListener(tipo, (ev) => {
      try { funcao(JSON.parse(ev.data)); } catch (e) { console.error("Evento inválido", tipo, e); }
    });
  }
  fonte.onopen = () => manipuladores.aberto && manipuladores.aberto();
  fonte.onerror = () => manipuladores.erro && manipuladores.erro();
  return fonte;
}
