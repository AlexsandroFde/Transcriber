// Integração com a janela do aplicativo (pywebview): seletores de arquivo nativos do Windows.
// Num navegador comum, as mesmas ações usam envio de arquivo ou um campo para colar o caminho.
import { api } from "./api.js";

let resolverPronto;
const pronto = new Promise((r) => (resolverPronto = r));
if (window.pywebview && window.pywebview.api) resolverPronto(true);
window.addEventListener("pywebviewready", () => resolverPronto(true), { once: true });
setTimeout(() => resolverPronto(!!(window.pywebview && window.pywebview.api)), 2500);

export const aguardarDesktop = () => pronto;
export const ehDesktop = () => !!(window.pywebview && window.pywebview.api);

async function ponte(metodo, ...args) {
  if (!(await pronto)) return undefined;
  try {
    return await window.pywebview.api[metodo](...args);
  } catch (e) {
    console.error("Falha na janela do aplicativo", metodo, e);
    return undefined;
  }
}

// Escolhe vídeos/áudios. Devolve caminhos no computador ou [] se a pessoa cancelar.
// `aoEnviar(nome, fracao)` informa o progresso do envio quando não há janela nativa.
export async function escolherMidias(aoEnviar) {
  if (await pronto) return (await ponte("escolher_midias")) || [];
  const arquivos = await escolherNoNavegador({ multiplos: true, aceitar: "video/*,audio/*,.mkv,.ts,.mts,.wma,.amr" });
  return enviarArquivos(arquivos, aoEnviar);
}

export async function enviarArquivos(arquivos, aoEnviar) {
  const caminhos = [];
  for (const arquivo of arquivos) {
    aoEnviar && aoEnviar(arquivo.name, 0);
    const enviado = await api.enviar(arquivo, (f) => aoEnviar && aoEnviar(arquivo.name, f));
    caminhos.push(enviado.caminho);
  }
  aoEnviar && aoEnviar(null, 1);
  return caminhos;
}

export async function escolherPasta(pedirCaminho) {
  if (await pronto) return (await ponte("escolher_pasta")) || null;
  return pedirCaminho({ titulo: "Pasta de destino", rotulo: "Caminho completo da pasta", exemplo: "C:\\Transcricoes" });
}

export async function escolherTranscricao(pedirCaminho) {
  if (await pronto) return (await ponte("escolher_arquivo", "json")) || null;
  return pedirCaminho({
    titulo: "Abrir transcrição", rotulo: "Caminho do arquivo .json da transcrição",
    exemplo: "C:\\Users\\voce\\Videos\\reuniao_transcricao\\reuniao.json",
  });
}

export async function escolherTexto(pedirCaminho) {
  if (await pronto) return (await ponte("escolher_arquivo", "txt")) || null;
  return pedirCaminho({ titulo: "Importar glossário", rotulo: "Caminho do arquivo .txt", exemplo: "C:\\glossario.txt" });
}

export async function abrirNoNavegador(url) {
  const absoluta = new URL(url, location.href).href;
  if (await pronto) return ponte("abrir_no_navegador", absoluta);
  window.open(absoluta, "_blank", "noopener");
}

function escolherNoNavegador({ multiplos, aceitar }) {
  return new Promise((resolver) => {
    const entrada = document.createElement("input");
    entrada.type = "file";
    entrada.multiple = multiplos;
    entrada.accept = aceitar;
    entrada.addEventListener("change", () => resolver([...entrada.files]));
    entrada.addEventListener("cancel", () => resolver([]));
    entrada.click();
  });
}
