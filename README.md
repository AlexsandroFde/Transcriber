# Transcritor de reuniões

Aplicativo que transcreve gravações de reuniões (vídeo ou áudio) em português brasileiro, com o
máximo de fidelidade ao que foi dito: identifica quem fala, marca o tempo de cada fala, preserva
hesitações e repetições, e **sinaliza o que não foi compreendido com segurança em vez de
adivinhar**. O resultado principal é sempre a transcrição completa. O programa não resume, não
reescreve e não transforma a reunião em ata.

Tudo roda no seu computador: o áudio da reunião não é enviado para nenhum serviço externo.

```
**[00:02:15] Participante 1:** Precisamos definir como será feita a integração com o sistema.

**[00:02:22] Participante 2:** Acredito que podemos utilizar a API que já está disponível.
```

O Transcritor tem três formas de uso, com as mesmas regras:

| Forma | Para quem |
|---|---|
| **Aplicativo** (atalho "Transcritor") | Uso diário, sem nenhum comando. |
| **API REST**, com documentação interativa em `/docs` | Outros programas e integrações. |
| **Linha de comando** (`transcritor ...`) | Automação e quem prefere o terminal. |

## O que você recebe

Para cada gravação, uma pasta `<nome do vídeo>_transcricao` ao lado do vídeo (ou na pasta que você escolher), com:

| Arquivo | Para que serve |
|---|---|
| `reuniao.docx` | Transcrição para ler, imprimir ou editar no Word. Trechos incertos destacados em amarelo. |
| `reuniao.md` e `reuniao.txt` | A mesma transcrição em texto simples. |
| `reuniao.srt` e `reuniao.vtt` | Legendas com o nome de quem fala, para abrir junto com o vídeo (VLC, YouTube etc.). |
| `reuniao_relatorio.md` | Relatório de conferência: pontos para ouvir de novo, tempo de fala por participante, sugestões de nomes e índice de menções a valores, datas e prazos. |
| `reuniao.json` | Dados completos (cada palavra com tempo e confiança). É a fonte para renomear participantes e gerar os arquivos de novo. |
| `reuniao.log` | Registro técnico do processamento. |

### Marcações usadas no texto

| Marcação | Significado |
|---|---|
| `[inaudível]` | Havia fala, mas não foi possível entender. |
| `[trecho incerto: ...]` | Melhor hipótese do sistema, sem confirmação. Confira na gravação; o relatório mostra as outras hipóteses ouvidas. |
| `[falas simultâneas com Participante X]` | A fala começou enquanto outra pessoa ainda falava (interrupção ou sobreposição). |
| `[falas simultâneas: Participante X]` | Outra pessoa falou ao mesmo tempo, e não foi possível transcrever o que ela disse. |

## Requisitos

- Windows 10 ou 11 (a API e a linha de comando também funcionam em Linux e macOS).
- Placa de vídeo NVIDIA com pelo menos 6 GB de memória (recomendado). Sem ela o programa usa
  o processador, mas fica cerca de 10 vezes mais lento.
- Cerca de 10 GB livres em disco (programa e modelos de IA).
- Internet apenas na instalação e na primeira execução (download dos modelos).

## Instalação

1. **Dê dois cliques em `instalar.bat`**, na pasta do programa. Ele faz tudo sozinho:
   instala o gerenciador de pacotes uv (se ainda não houver), os componentes do programa
   (cerca de 3 GB na primeira vez), cria o atalho **Transcritor** na Área de Trabalho e no menu
   Iniciar e abre o aplicativo, que baixa os modelos de IA mostrando o andamento na janela.
2. Pronto. Nas próximas vezes, abra pelo atalho **Transcritor**.

Para atualizar o programa (depois de copiar uma versão nova da pasta), feche o Transcritor e
execute o `instalar.bat` de novo.

### Opcional: modelo mais recente de identificação de participantes

Sem nenhuma configuração, o programa já usa o pipeline pyannote 3.1, montado com componentes de
acesso livre (nos testes, acertou o número de participantes sozinho e atribuiu 95% a 97% das
falas corretamente). O modelo mais novo do pyannote (community-1) é gratuito, mas exige uma conta
no Hugging Face. No aplicativo, abra **Configurações > Identificação avançada de participantes**
e siga os três passos indicados (criar a conta, aceitar os termos do modelo e colar um token de
leitura). O Transcritor verifica o acesso na hora.

## Como usar o aplicativo

### Transcrever

1. **Arraste o vídeo** (ou áudio) para a janela do Transcritor, ou sobre o atalho na Área de
   Trabalho, ou clique na área "Arraste um vídeo ou áudio para cá" para escolher no computador.
   Dá para escolher vários arquivos de uma vez: eles entram numa fila e são transcritos em sequência.
2. Na tela **Nova transcrição**, informe o que souber (tudo é opcional, mas melhora o resultado):
   quantas pessoas falam, o assunto da reunião e o glossário (nomes, siglas e termos técnicos).
   O glossário padrão, sugerido em toda transcrição nova, fica em **Configurações**.
3. Escolha onde salvar (ao lado da gravação ou em outra pasta) e os formatos.
4. Clique em **Transcrever**. A tela de acompanhamento mostra as seis etapas, o percentual, a
   mensagem atual e o tempo restante estimado. Você pode continuar usando o computador.

As **Opções avançadas** cobrem todos os parâmetros do processamento: faixa de áudio (aparece
quando o vídeo tem mais de uma, como nas gravações do OBS), modelo de reconhecimento, modelo da
revisão, identificação de participantes, estilo do texto (literal ou padrão), tratamento do áudio,
dispositivo, precisão numérica, largura do feixe, limiar de incerteza, revisão em segundo passo,
refazer todas as etapas, manter os áudios intermediários e registro detalhado. Cada opção traz a
explicação do que faz.

**Interrupções:** cancelar uma transcrição, fechar o aplicativo (ele pede confirmação) ou uma queda
de energia não perdem o trabalho feito. Em **Atividades**, a tarefa aparece como interrompida;
**Retomar** continua de onde parou, reaproveitando as etapas concluídas.

### Depois da transcrição

Em **Transcrições**, cada transcrição tem quatro abas:

| Aba | O que faz |
|---|---|
| **Texto** | A transcrição com os trechos incertos destacados e busca (sem diferenciar acentos). Clique em qualquer horário para ouvir aquele ponto da gravação. Com a **Rolagem automática** ligada, a tela rola até cada fala quando ela começa e o vídeo fica fixo no alto; se você rolar a página durante a reprodução, o acompanhamento pausa até você clicar em **Voltar ao trecho atual** (ou em um horário do texto). A escolha fica guardada. |
| **Participantes** | Dá nome a cada participante. Mostra exemplos do que cada pessoa disse e os nomes mencionados na conversa (por exemplo, quando alguém diz "aqui é a Mariana"); um clique usa a sugestão. Se a mesma pessoa apareceu com dois rótulos, escolha "É a mesma pessoa que". Ao salvar, todos os arquivos são gerados de novo. O programa nunca atribui nomes sozinho. |
| **Conferência** | Indicadores de qualidade, os pontos para ouvir de novo (trechos incertos, com as outras hipóteses ouvidas, inaudíveis e frases descartadas), as sugestões de nomes e o índice de menções a valores, datas, prazos, horários, percentuais e encaminhamentos. Tudo são citações literais. |
| **Arquivos** | Abre os arquivos gerados (Word, textos, legendas) e gera os arquivos de novo, em outros formatos ou em outra pasta. |

Transcrições feitas antes (pela versão antiga, com o `.bat`, ou pela linha de comando) podem ser
abertas em **Transcrições > Abrir transcrição existente**, escolhendo o arquivo `.json` da pasta delas.

### Dicas para a melhor transcrição

- **Informe o número de participantes** quando souber, principalmente se houver vozes parecidas.
- **Monte um glossário** com os nomes das pessoas, da organização, de projetos e siglas.
  Na reunião de teste, o glossário corrigiu "CIGEP" para "SIGEP" em todas as ocorrências.
- **Descreva o assunto** da reunião.
- Se o vídeo tiver várias faixas de áudio, escolha a que contém a conversa completa ou misture todas.

## API REST e integrações

Com o aplicativo aberto, a API fica em `http://127.0.0.1:8765/api/v1` e a documentação interativa
(Swagger UI, funciona sem internet) em **http://127.0.0.1:8765/docs**, também acessível em
**Configurações > Sobre > Documentação da API**. Para usar só a API, sem janela:

```
uv run transcritor servidor              # 127.0.0.1:8765; --porta e --host mudam o endereço
```

A interface do aplicativo usa exclusivamente esta API. As operações demoradas são assíncronas:

1. `POST /api/v1/transcricoes` responde na hora (**202**) com uma tarefa por arquivo. Erros simples
   (arquivo inexistente, sem áudio, faixa que não existe) já são recusados nesta chamada (**422**).
2. Acompanhe por `GET /api/v1/tarefas/{id}` (estado, etapas, percentual, tempo restante) ou pelos
   eventos em tempo real de `GET /api/v1/eventos` (Server-Sent Events).
3. Quando `estado` vira `concluida`, `resultado.transcricao_id` leva aos detalhes, ao texto, ao
   relatório e aos arquivos.

```python
import time, httpx

api = httpx.Client(base_url="http://127.0.0.1:8765/api/v1")
tarefa = api.post("/transcricoes", json={"arquivos": [r"C:\Videos\reuniao.mp4"], "participantes": 4}).json()["tarefas"][0]
while (tarefa := api.get(f"/tarefas/{tarefa['id']}").json())["estado"] in ("na_fila", "em_andamento"):
    print(f"{tarefa['progresso']['percentual']:.0f}%", tarefa["progresso"]["mensagem"])
    time.sleep(2)
id_ = tarefa["resultado"]["transcricao_id"]
print(api.get(f"/transcricoes/{id_}/arquivos/md").text)
```

| Categoria | Rotas principais |
|---|---|
| Transcrições | `POST /transcricoes`, `GET /transcricoes`, `GET /transcricoes/{id}`, `/conteudo`, `/relatorio`, `/arquivos/{tipo}`, `/midia`, `POST /transcricoes/importacoes`, `DELETE /transcricoes/{id}` |
| Tarefas | `GET /tarefas`, `GET /tarefas/{id}`, `POST /tarefas/{id}/cancelar`, `POST /tarefas/{id}/repetir`, `GET /tarefas/{id}/registro`, `DELETE /tarefas/{id}` |
| Participantes e exportação | `GET` e `PATCH /transcricoes/{id}/participantes`, `POST /transcricoes/{id}/exportacoes` |
| Mídia | `GET /midia/informacoes`, `POST /midia/envios` (para quem não compartilha o disco), `GET` e `DELETE /midia/envios` |
| Ambiente e configuração | `GET /ambiente`, `POST /ambiente/verificacoes`, `POST /ambiente/modelos/downloads`, token do Hugging Face e glossário padrão em `/configuracao` |
| Sistema | `GET /saude`, `GET /sistema`, `GET /opcoes` (valores aceitos e padrões), `POST /sistema/abrir`, `POST /sistema/encerrar`, `GET /eventos` |

Toda resposta de erro tem o mesmo formato: `{"erro": {"codigo", "status", "mensagem", "dica", "campos"}}`,
com um `codigo` estável para integrações e uma `mensagem` e uma `dica` escritas para pessoas.

**Segurança:** a API atende só este computador (127.0.0.1) e recusa pedidos feitos por outros sites
abertos no navegador. Ela não tem autenticação: não a exponha na rede sem uma camada própria de proteção.

## Linha de comando

```
uv run transcritor reuniao.mp4
uv run transcritor reuniao.mp4 -n 5 -c "Reunião do conselho sobre o orçamento 2027" -g glossario.txt
uv run transcritor *.mp4 -s C:\Transcricoes
uv run transcritor nomear reuniao_transcricao\reuniao.json "Participante 1=Ana Souza" "Participante 2=Carlos"
uv run transcritor nomear reuniao_transcricao\reuniao.json --interativo
uv run transcritor exportar reuniao_transcricao\reuniao.json -f docx,srt
uv run transcritor verificar --baixar-modelos
uv run transcritor configurar-token hf_SEU_TOKEN
uv run transcritor app                   # abre o aplicativo
```

| Opção de `transcrever` | Efeito |
|---|---|
| `-n 5` | Número exato de participantes, quando conhecido. |
| `--min-participantes` / `--max-participantes` | Limites, quando o número exato não é conhecido. |
| `-c "texto"` | Assunto da reunião (organização, projeto, tema). |
| `-g arquivo.txt` | Glossário: nomes, siglas e termos, um por linha (vários separados por `;`; `#` inicia comentário). |
| `-s pasta` | Pasta de saída. |
| `-f docx,srt` | Só os formatos escolhidos (`md,txt,docx,srt,vtt,json`). |
| `--faixa-audio 1` ou `todas` | Escolhe a faixa de áudio quando o vídeo tem mais de uma. |
| `--pre-processamento` | `auto` (padrão), `leve`, `forte` ou `nenhum`. |
| `--diarizacao` | `auto` (padrão), `pyannote` (community-1, com token), `livre` (pyannote 3.1 sem token), `sherpa` ou `nenhuma`. |
| `--sem-revisao` | Pula o segundo passo de revisão. Mais rápido, menos preciso. |
| `--estilo padrao` | Deixa o modelo decidir sobre hesitações (o padrão `literal` as preserva). |
| `--modelo large-v3-turbo` / `--modelo-revisao` | Modelo mais rápido / modelo diferente no segundo passo. |
| `--dispositivo`, `--precisao`, `--beam`, `--limiar-incerteza` | Ajustes finos do reconhecimento. |
| `--refazer`, `--manter-audio`, `-v` | Ignora o cache, guarda os WAV intermediários, registro detalhado. |

No `nomear`, dar a um rótulo o nome de outro rótulo une os dois (`"Participante 5=Participante 4"`);
`--arquivo` lê os pares de um `.txt` e `--limpar` remove todos os nomes.

## Como funciona

1. **Extração do áudio** com o ffmpeg, sem compressão com perdas.
2. **Tratamento do áudio**: canal mudo ou com fase invertida fica fora da mixagem; filtro
   passa-altas e normalização de volume. Redução de ruído e normalização dinâmica só são
   aplicadas quando as medições indicam necessidade, porque filtros agressivos criam
   artefatos que pioram o reconhecimento.
3. **Identificação dos participantes** (diarização) com pyannote, incluindo falas
   simultâneas: o modelo community-1 quando há token; sem token, o pipeline do pyannote 3.1
   com o modelo de segmentação 3.0 (licença MIT, na cópia em ONNX do projeto sherpa-onnx), o
   embedding de voz WeSpeaker e os parâmetros publicados do 3.1.
4. **Transcrição** com o Whisper large-v3 (o modelo aberto mais preciso documentado para
   português), apenas nos trechos com fala, em sequência contínua para preservar o contexto.
   O contexto da reunião, o glossário e um trecho de exemplo coloquial orientam o modelo a
   transcrever de forma literal.
5. **Filtro de alucinações**: frases que o Whisper costuma inventar em silêncio ou ruído
   ("Legendas pela comunidade Amara.org", "Obrigado por assistir") são descartadas quando
   não há evidência de fala, e ficam registradas no relatório.
6. **Revisão em segundo passo**: cada trecho duvidoso é decodificado mais duas vezes em
   condições diferentes. As três versões são comparadas palavra a palavra: o que a maioria
   confirma fica; o que só uma versão "ouviu" sai; nada do primeiro passo é apagado sem aviso;
   e o que não tem maioria vira `[trecho incerto: ...]`.
7. **Montagem**: cada palavra é atribuída a quem estava falando naquele instante; interrupções
   e falas simultâneas são marcadas; turnos longos são divididos em parágrafos.

Cada etapa grava seu resultado em `.trabalho`, dentro da pasta de saída: ao processar de novo a
mesma gravação, as etapas já concluídas são reaproveitadas.

## Arquitetura

```
 Janela (pywebview + WebView2)       Outros programas        Linha de comando
   interface web (src/transcritor/web)        │                 (cli.py)
          │ HTTP + eventos (SSE)              │ HTTP                │
          ▼                                   ▼                     │
   API REST FastAPI (api/)  ── rotas, contratos, erros, /docs        │
          │                                                         │
          ▼                                                         ▼
   Serviços (servicos/) ── casos de uso, validação, fila de tarefas, histórico (SQLite)
          │                         │
          │                         └─► processo trabalhador (trabalhador.py), um por tarefa:
          ▼                             transcrição, verificação, download de modelos
   Núcleo de processamento (processamento/) ── áudio, diarização, Whisper, revisão, montagem, exportação
```

- Toda regra de negócio está nos serviços e no núcleo; a interface e a CLI só traduzem entradas e saídas.
- Transcrições rodam uma de cada vez num processo separado: cancelar encerra o processo (e o
  ffmpeg), a memória da placa de vídeo é devolvida ao fim de cada tarefa e uma falha nativa não
  derruba o aplicativo. No Windows, cada processo entra num Job Object: se o aplicativo terminar
  por qualquer motivo, nada fica rodando em segundo plano.
- O inicializador (`desktop/`) garante uma única instância, sobe a API numa porta livre de
  127.0.0.1, mostra a janela quando ela está pronta e, ao fechar, encerra as tarefas, as conexões e libera a porta.

| Pasta | Conteúdo |
|---|---|
| `src/transcritor/processamento/` | `audio`, `diarizacao`, `asr`, `qualidade`, `revisao`, `montagem`, `exportar`, `relatorio`, `nomes`, `documento` (leitura do JSON e geração das saídas) e `pipeline` (orquestração com cache por etapa). |
| `src/transcritor/servicos/` | `contratos` (modelos de entrada e saída), `transcricoes`, `participantes`, `glossario`, `midia`, `diagnostico`, `configuracao`, `sistema`, `catalogo`, `tarefas`, `execucao`, `progresso`, `eventos`, `repositorio` e `contexto`. |
| `src/transcritor/api/` | Aplicação FastAPI, rotas por categoria, formato de erro, proteção local e documentação. |
| `src/transcritor/desktop/` | Janela, instância única, páginas de abertura e de erro, atalhos e o lançador que abre o aplicativo sem janela de console. |
| `src/transcritor/web/` | Interface (HTML, CSS e JavaScript em módulos, sem etapa de build). |
| `config.py`, `erros.py`, `ambiente.py` | Configurações centralizadas, erros com mensagens para pessoas, ambiente de execução. |

Configurações ajustáveis por variáveis de ambiente (`TRANSCRITOR_PORTA`, `TRANSCRITOR_HOST`,
`TRANSCRITOR_PASTA_DADOS` e outras) estão descritas em `src/transcritor/config.py`.

## Privacidade

- O processamento é local. Os modelos são baixados uma vez e ficam em cache.
- A API atende só este computador. A telemetria das bibliotecas é desligada pelo programa (o
  pyannote envia métricas de uso por padrão; aqui isso é desativado).
- Os arquivos de áudio intermediários são apagados ao final (opção "Manter os áudios
  intermediários" para guardá-los).
- O histórico do aplicativo e os registros ficam em `%LOCALAPPDATA%\transcritor`; o token do
  Hugging Face e o glossário padrão, em `%APPDATA%\transcritor`.

## Desempenho medido

Computador de referência: RTX 4060 (8 GB), Ryzen 7 8700F, 16 GB de RAM.

| Gravação | Tempo total de processamento |
|---|---|
| Reunião de 2 min | cerca de 1 min |
| Reunião de 32 min | de 6 a 10 min (variou com o uso do computador durante o teste) |

O tempo cresce de forma proporcional à duração: conte com algo entre um quinto e um terço da
duração da gravação. Sem placa de vídeo, o processamento é bem mais lento.

Qualidade em reuniões de teste com gabarito (4 participantes, vozes sintéticas, com
interrupção sobreposta, respostas curtas, um participante com volume baixo, ruído de fundo
e 8 s de silêncio), sem informar o número de participantes:

| Medida | Reunião de 2 min | Reunião de 32 min |
|---|---|---|
| Taxa de erro de palavras (com glossário, pipeline livre) | 0% | 0,9% |
| Taxa de erro de palavras (com glossário, community-1) | 0,4% (uma palavra já sinalizada como incerta) | não medida |
| Taxa de erro de palavras (sem glossário) | 1,4% (a sigla SIGEP) | não medida |
| Número de participantes detectado | 4 (correto) | 4 (correto) |
| Palavras atribuídas à pessoa certa | 97% | 97% |
| Alucinações no silêncio | nenhuma | nenhuma |

Vozes sintéticas são mais fáceis que gravações reais; os números servem para validar o
funcionamento, não como promessa de desempenho em qualquer reunião.

## Limitações conhecidas

- Quando duas pessoas falam ao mesmo tempo, normalmente só a voz dominante é transcrita;
  o trecho da outra fica marcado como fala simultânea.
- A separação de vozes pode errar com vozes parecidas, falas muito curtas ou pessoas que
  falam longe do microfone. Rótulos duplicados para a mesma pessoa se corrigem na aba Participantes.
- A sinalização de incerteza é estatística: reduz muito, mas não elimina, erros não
  sinalizados. Para documentos com valor formal, confira os pontos listados na aba Conferência.
- Números podem aparecer em algarismos ou por extenso, conforme o modelo transcrever.
- Alguns formatos de vídeo (por exemplo, certos MKV) não tocam dentro do aplicativo; nesse caso,
  ele oferece abrir a gravação no player do sistema.

## Solução de problemas

| Sintoma | O que fazer |
|---|---|
| "Sem placa de vídeo compatível" | Atualize o driver da NVIDIA. Sem placa, escolha o modelo large-v3-turbo nas Opções avançadas para ganhar velocidade. |
| "Acesso negado ao modelo" | Em Configurações, confira o token e se os termos foram aceitos com a mesma conta. Enquanto isso, o programa usa o pipeline livre. |
| Mais participantes do que o real | Informe o número exato ou una os rótulos na aba Participantes. |
| Pessoas diferentes no mesmo rótulo | Transcreva de novo informando o número exato de participantes. |
| "Faltou memória na placa de vídeo" | Nas Opções avançadas, escolha a precisão int8_float16. |
| Vídeo com várias faixas de áudio | Nas Opções avançadas, escolha a faixa certa ou misture todas. |
| O aplicativo não abre ou mostra erro ao iniciar | Use "Tentar de novo". Se continuar, execute o `instalar.bat` outra vez; os registros ficam em `%LOCALAPPDATA%\transcritor\logs`. |
| "O Transcritor já está aberto, mas não respondeu" | Aguarde alguns segundos e abra de novo; se continuar, encerre o processo pelo Gerenciador de Tarefas. |

## Modelos e licenças

| Componente | Uso | Licença |
|---|---|---|
| Whisper large-v3 (OpenAI), via faster-whisper | Reconhecimento de fala | MIT |
| pyannote speaker-diarization-community-1 | Diarização (com token) | CC-BY-4.0 |
| pyannote segmentation-3.0, cópia ONNX do sherpa-onnx | Diarização livre | MIT |
| WeSpeaker ResNet34-LM (pyannote/wespeaker-voxceleb-resnet34-LM) | Diarização livre | CC-BY-4.0 |
| NVIDIA TitaNet small, via sherpa-onnx | Diarização de último recurso | CC-BY-4.0 |
| Silero VAD (incluso no faster-whisper) | Detecção de fala | MIT |
| ffmpeg (imageio-ffmpeg) | Extração e filtros de áudio | GPL/LGPL |
| FastAPI, Uvicorn, pywebview | API e janela do aplicativo | MIT / BSD-3-Clause |
| Preact e htm (incluídos em `web/vendor`) | Interface | MIT / Apache-2.0 |
| Swagger UI (incluído em `web/vendor`) | Documentação da API | Apache-2.0 |

## Para quem mantém o código

```
uv sync                       # instala dependências, inclusive as de desenvolvimento
uv run pytest                 # testes (lógica, serviços, API e CLI; sem modelos de IA)
uv run transcritor app        # abre o aplicativo a partir do terminal (TRANSCRITOR_DEPURAR=1 abre as ferramentas do navegador)
uv run transcritor servidor   # só a API
uv run python ferramentas/gerar_reuniao_teste.py amostras        # reunião sintética com gabarito
uv run transcritor amostras/reuniao_teste.mp4 -s saida -g glossario_exemplo.txt
uv run python ferramentas/avaliar.py saida/reuniao_teste/reuniao_teste.json amostras/reuniao_teste_gabarito.json
uv run python ferramentas/gerar_icone.py                         # só se o desenho do ícone mudar
```

Os testes da API usam um processo trabalhador falso (`tests/trabalhador_falso.py`), que fala o mesmo
protocolo do verdadeiro sem carregar modelos. Ao mexer em `servicos/execucao.py` ou em
`trabalhador.py`, confira também com uma tarefa real (a verificação do ambiente leva cerca de 10 s):
há armadilhas do Windows que só aparecem com as bibliotecas nativas, descritas nos comentários desses módulos.
