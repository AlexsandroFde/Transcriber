"""Serviços (casos de uso) da aplicação.

Ficam entre as interfaces (API REST, linha de comando, janela) e o núcleo de processamento.
Toda regra de negócio está aqui ou no núcleo; as interfaces apenas traduzem entradas e saídas.

  * `contratos`: modelos de dados de entrada e saída (validação e documentação);
  * `transcricoes`, `participantes`, `glossario`, `midia`: casos de uso das transcrições;
  * `diagnostico`, `configuracao`, `sistema`: ambiente, token, glossário padrão e sistema;
  * `tarefas`, `execucao`, `progresso`, `eventos`, `repositorio`: execução assíncrona,
    acompanhamento, notificações e histórico;
  * `contexto`: montagem de tudo isso.
"""
