# Transcritor de reuniões

Transcreve gravações de reuniões (vídeo ou áudio) em português brasileiro, com o máximo de
fidelidade ao que foi dito: identifica quem fala, marca o tempo de cada fala, preserva
hesitações e repetições, e **sinaliza o que não foi compreendido com segurança em vez de
adivinhar**. O resultado principal é sempre a transcrição completa. O programa não resume,
não reescreve e não transforma a reunião em ata.

Tudo roda no seu computador: o áudio da reunião não é enviado para nenhum serviço externo.

```
**[00:02:15] Participante 1:** Precisamos definir como será feita a integração com o sistema.

**[00:02:22] Participante 2:** Acredito que podemos utilizar a API que já está disponível.

**[00:02:31] Participante 1:** Certo. E qual seria o prazo para implementar isso?
```

## O que você recebe

Para cada gravação, uma pasta `<nome do vídeo>_transcricao` ao lado do vídeo, com:

| Arquivo | Para que serve |
|---|---|
| `reuniao.docx` | Transcrição para ler, imprimir ou editar no Word. Trechos incertos destacados em amarelo. |
| `reuniao.md` e `reuniao.txt` | A mesma transcrição em texto simples. |
| `reuniao.srt` e `reuniao.vtt` | Legendas com o nome de quem fala, para abrir junto com o vídeo (VLC, YouTube etc.). |
| `reuniao_relatorio.md` | Relatório de conferência: pontos para ouvir de novo, tempo de fala por participante, sugestões de nomes e índice de menções a valores, datas e prazos. |
| `reuniao.json` | Dados completos (cada palavra com tempo e confiança). Usado para renomear participantes e regenerar os arquivos. |
| `reuniao.log` | Registro técnico do processamento. |

### Marcações usadas no texto

| Marcação | Significado |
|---|---|
| `[inaudível]` | Havia fala, mas não foi possível entender. |
| `[trecho incerto: ...]` | Melhor hipótese do sistema, sem confirmação. Confira na gravação; o relatório mostra as outras hipóteses ouvidas. |
| `[falas simultâneas com Participante X]` | A fala começou enquanto outra pessoa ainda falava (interrupção ou sobreposição). |
| `[falas simultâneas: Participante X]` | Outra pessoa falou ao mesmo tempo, e não foi possível transcrever o que ela disse. |

## Requisitos

- Windows 10 ou 11 (também funciona em Linux e macOS pela linha de comando).
- Placa de vídeo NVIDIA com pelo menos 6 GB de memória (recomendado). Sem ela o programa usa
  o processador, mas fica cerca de 10 vezes mais lento.
- Cerca de 10 GB livres em disco (programa e modelos de IA).
- Internet apenas na instalação e na primeira execução (download dos modelos).

## Instalação

1. **Instale o uv** (gerenciador do Python), se ainda não tiver. Abra o PowerShell e execute:

   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

2. **Dê dois cliques em `instalar.bat`.** Ele instala tudo (cerca de 3 GB na primeira vez),
   verifica a placa de vídeo e baixa os modelos.

3. **Opcional: habilite o modelo mais recente de identificação de participantes.** Sem
   nenhuma configuração, o programa já usa o pipeline pyannote 3.1, montado com componentes
   de acesso livre (nos testes, acertou o número de participantes sozinho e atribuiu 95% a
   97% das falas corretamente). O modelo mais novo do pyannote (community-1) é gratuito, mas
   exige uma conta no Hugging Face:
   1. Crie uma conta em <https://huggingface.co/join>.
   2. Abra <https://huggingface.co/pyannote/speaker-diarization-community-1> e aceite os
      termos de uso (botão no topo da página).
   3. Gere um token de leitura em <https://huggingface.co/settings/tokens>.
   4. No terminal, dentro da pasta do programa, rode:

      ```
      uv run transcritor configurar-token hf_SEU_TOKEN_AQUI
      uv run transcritor verificar
      ```

## Como usar

### Jeito mais simples

Arraste o arquivo de vídeo (ou áudio) sobre **`transcrever.bat`**. Ele pergunta o número de
participantes e o assunto da reunião (os dois são opcionais, mas melhoram o resultado) e, ao
final, abre a pasta com os arquivos.

Se existir um arquivo `glossario.txt` na pasta do programa, ele é usado automaticamente
(veja `glossario_exemplo.txt`).

### Pela linha de comando

```
uv run transcritor reuniao.mp4
uv run transcritor reuniao.mp4 -n 5 -c "Reunião do conselho sobre o orçamento 2027" -g glossario.txt
uv run transcritor *.mp4 -s C:\Transcricoes
```

Principais opções:

| Opção | Efeito |
|---|---|
| `-n 5` | Número exato de participantes, quando conhecido. Ajuda a separar vozes parecidas. |
| `--min-participantes` / `--max-participantes` | Limites, quando o número exato não é conhecido. |
| `-c "texto"` | Assunto da reunião (organização, projeto, tema). Ajuda a reconhecer o vocabulário. |
| `-g arquivo.txt` | Glossário: nomes de pessoas, siglas e termos técnicos, um por linha. |
| `-s pasta` | Pasta de saída. |
| `-f docx,srt` | Só os formatos escolhidos (`md,txt,docx,srt,vtt,json`). |
| `--faixa-audio 1` ou `todas` | Escolhe a faixa de áudio quando o vídeo tem mais de uma (ex.: OBS). |
| `--pre-processamento` | `auto` (padrão), `leve`, `forte` ou `nenhum`. |
| `--diarizacao` | `auto` (padrão), `pyannote` (community-1, com token), `livre` (pyannote 3.1 sem token), `sherpa` ou `nenhuma`. |
| `--sem-revisao` | Pula o segundo passo de revisão. Mais rápido, menos preciso. |
| `--estilo padrao` | Deixa o modelo decidir sobre hesitações (o padrão `literal` as preserva). |
| `--modelo large-v3-turbo` | Modelo mais rápido, um pouco menos preciso (útil sem placa de vídeo). |
| `--refazer` | Ignora resultados anteriores e processa tudo de novo. |

Se o processamento for interrompido (queda de energia, janela fechada), basta rodar de novo:
as etapas concluídas são reaproveitadas.

### Dicas para a melhor transcrição

- **Informe o número de participantes** (`-n`) quando souber, principalmente se houver vozes
  parecidas.
- **Monte um glossário** com os nomes das pessoas, da organização, de projetos e siglas.
  Na reunião de teste, o glossário corrigiu "CIGEP" para "SIGEP" em todas as ocorrências.
- **Descreva o assunto** com `-c`.
- Se o vídeo tiver várias faixas de áudio (gravações do OBS, por exemplo), escolha a que
  contém a mixagem completa ou use `--faixa-audio todas`.

## Depois da transcrição

### Dar nome aos participantes

O programa nunca atribui nomes por conta própria. Para associar os rótulos às pessoas,
arraste o arquivo `.json` sobre **`nomear.bat`**: para cada participante ele mostra exemplos
do que a pessoa disse e os nomes mencionados na conversa (por exemplo, quando alguém diz
"aqui é a Mariana"), e pergunta o nome. Pela linha de comando:

```
uv run transcritor nomear reuniao_transcricao\reuniao.json "Participante 1=Ana Souza" "Participante 2=Carlos"
uv run transcritor nomear reuniao_transcricao\reuniao.json --interativo
```

Se uma mesma pessoa aparecer com dois rótulos, una-os dando a um deles o rótulo do outro:
`"Participante 5=Participante 4"`. Todos os arquivos são regenerados na hora.

### Conferência

Abra o `_relatorio.md`. A seção **Pontos para conferência** lista, com o tempo exato, cada
trecho incerto (com as outras hipóteses que o sistema ouviu), cada trecho inaudível e cada
frase descartada como alucinação do modelo. O **Índice de menções** reúne as frases com
valores, datas, prazos, horários, percentuais e encaminhamentos, que são as informações que
mais exigem exatidão. Tudo são citações literais da transcrição.

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
6. **Revisão em segundo passo**: cada trecho duvidoso (palavras de baixa confiança, palavras
   com aparência de inventadas, respostas curtas, repetições em laço, fala detectada sem
   texto) é decodificado mais duas vezes em condições diferentes. As três versões são
   comparadas palavra a palavra: o que a maioria confirma fica; o que só uma versão "ouviu"
   sai; nada do primeiro passo é apagado sem aviso; e o que não tem maioria vira
   `[trecho incerto: ...]`. Termos ditos com clareza em outros momentos da própria reunião
   entram como vocabulário de apoio.
7. **Montagem**: cada palavra é atribuída a quem estava falando naquele instante; interrupções
   e falas simultâneas são marcadas; turnos longos são divididos em parágrafos com novo
   marcador de tempo.

## Privacidade

- O processamento é local. Os modelos são baixados uma vez e ficam em cache.
- A telemetria das bibliotecas é desligada pelo programa (o pyannote envia métricas de uso
  por padrão; aqui isso é desativado).
- Os arquivos de áudio intermediários são apagados ao final (use `--manter-audio` para
  guardá-los). Os resultados ficam em `.trabalho`, dentro da pasta de saída.

## Desempenho medido

Computador de referência: RTX 4060 (8 GB), Ryzen 7 8700F, 16 GB de RAM.

| Gravação | Tempo total de processamento |
|---|---|
| Reunião de 2 min | cerca de 1 min |
| Reunião de 32 min | de 6 a 10 min (variou com o uso do computador durante o teste) |

O tempo cresce de forma proporcional à duração: conte com algo entre um quinto e um terço da
duração da gravação. Sem placa de vídeo, o processamento é bem mais lento (veja a seção de
requisitos).

Qualidade em reuniões de teste com gabarito (4 participantes, vozes sintéticas, com
interrupção sobreposta, respostas curtas, um participante com volume baixo, ruído de fundo
e 8 s de silêncio), sem token e sem informar o número de participantes:

| Medida | Reunião de 2 min | Reunião de 32 min |
|---|---|---|
| Taxa de erro de palavras (com glossário) | 0% | 0,9% |
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
  falam longe do microfone. Rótulos duplicados para a mesma pessoa se corrigem com `nomear`.
- A sinalização de incerteza é estatística: reduz muito, mas não elimina, erros não
  sinalizados. Para documentos com valor formal, confira os pontos listados no relatório.
- Números podem aparecer em algarismos ou por extenso, conforme o modelo transcrever.

## Solução de problemas

| Sintoma | O que fazer |
|---|---|
| "GPU (CUDA): indisponível" | Atualize o driver da NVIDIA. Sem GPU, use `--modelo large-v3-turbo` para ganhar velocidade. |
| "Acesso negado ao modelo pyannote" | Confira se aceitou os termos na página do modelo com a mesma conta do token. Enquanto isso, o programa usa o pipeline livre. |
| Mais participantes do que o real | Informe `-n` ou una rótulos com `nomear`. |
| Pessoas diferentes no mesmo rótulo | Rode de novo com `-n` igual ao número real de participantes. |
| Falta memória na placa de vídeo | Use `--precisao int8_float16`. |
| Vídeo com várias faixas de áudio | Use `--faixa-audio todas` ou o índice da faixa certa. |

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

## Para quem mantém o código

```
uv sync                       # instala dependências, inclusive as de desenvolvimento
uv run pytest                 # testes da lógica (sem modelos)
uv run python ferramentas/gerar_reuniao_teste.py amostras        # reunião sintética com gabarito
uv run transcritor amostras/reuniao_teste.mp4 -s saida -g glossario_exemplo.txt
uv run python ferramentas/avaliar.py saida/reuniao_teste/reuniao_teste.json amostras/reuniao_teste_gabarito.json
```

Estrutura de `src/transcritor/`:

| Módulo | Responsabilidade |
|---|---|
| `audio.py` | Extração, análise de canais, medições, pré-processamento adaptativo, VAD. |
| `diarizacao.py` | pyannote community-1 (token), pipeline pyannote 3.1 livre e sherpa-onnx (último recurso). |
| `asr.py` | Whisper via faster-whisper; concatenação dos trechos de fala e mapeamento de tempos. |
| `qualidade.py` | Alucinações, laços, diagnóstico de segmentos e votação entre hipóteses. |
| `revisao.py` | Segundo passo: alvos, janelas sem cortar palavras e três decodificações. |
| `montagem.py` | Atribuição de falantes, falas simultâneas e parágrafos. |
| `exportar.py`, `relatorio.py`, `nomes.py` | Formatos de saída, relatório e sugestões de nomes. |
| `pipeline.py`, `cli.py` | Orquestração com cache por etapa e linha de comando. |
