# Medir agentes

`mede_agente.py` lê o transcript JSONL que o Claude Code grava para cada agente e diz quanto ele
custou e onde o tempo foi. Sem medir, a discussão sobre agente lento ou caro vira palpite.

## Onde estão os transcripts

```
~/.claude/projects/<projeto>/<sessao>.jsonl                      # a sessão principal
~/.claude/projects/<projeto>/<sessao>/subagents/agent-<id>.jsonl  # cada subagente
```

`<projeto>` é o caminho do diretório com `/` trocado por `-`. O arquivo é gravado ao vivo: dá para
medir um agente que ainda está rodando.

```bash
S=~/.claude/skills/dev-agentes/scripts
python $S/mede_agente.py ~/.claude/projects/<projeto>/<sessao>/subagents/     # todos
python $S/mede_agente.py agent-abc.jsonl --lentas 5
python $S/mede_agente.py pasta/ --json > medidas.json
```

## A tabela de custo

| coluna | o que é | sinal |
|---|---|---|
| `requisicoes` | chamadas ao modelo | muito acima do combinado: escopo aberto |
| `entrada_total` | soma do contexto de todas as requisições | cresce com o quadrado do tamanho da conversa |
| `contexto_max` | maior contexto numa requisição | acima de uns 150 mil: histórico pesado, imagem ou saída sem filtro |
| `saida` | tokens gerados | alto com pouco resultado: o agente está escrevendo e reescrevendo |
| `imagens_lidas` | leituras de PNG/JPG/WebP | cada uma fica no contexto até o fim |
| `custo_usd` | estimativa pela tabela pública, com cache | vazio quando o modelo não está na tabela |

No `--json` há ainda `bytes_de_resultado` por ferramenta: qual ferramenta mais encheu o contexto.

A tabela de preços (`PRECO_POR_MTOK`) é a pública na data em que o script foi escrito; confira e
atualize quando os preços mudarem. Cada linha tem a entrada, a saída e o fator da leitura de cache
(0,1 na maioria, 0,05 no Opus 5.5, 0,025 no Fable 5.1), e vale o prefixo mais longo que casa com o
id do modelo: `claude-opus-5-5` não cai no preço do `claude-opus-5`. A escrita de cache de 1 hora
conta 2x a entrada e a de 5 minutos, 1,25x.

Modelo fora da tabela não vira custo zero: o `custo_usd` do agente fica vazio, o `--json` traz
`sem_preco` (modelo e requisições) e `custo_parcial_usd` (só o que tem preço), e sai um aviso no
stderr. Para dar o preço sem editar o script:

```bash
python $S/mede_agente.py pasta/ --preco claude-fable-5-2=10,50,0.025   # entrada,saída[,leitura]
MEDE_AGENTE_PRECOS=precos.json python $S/mede_agente.py pasta/         # {"modelo": [10, 50, 0.025]}
```

A linha de comando passa por cima do arquivo, e o arquivo, da tabela. O preço do
`claude-fable-5-2` na tabela é o do Fable 5.1, assumido: o script avisa toda vez que o usa.

## O tempo

```
TEMPO POR AGENTE (min): parede, modelo, ferramentas e as 3 categorias maiores
FERRAMENTAS POR CATEGORIA (soma de todos)
CHAMADAS MAIS LENTAS
PENDURADAS (sem resultado, ou a 90% do prazo)
```

- **parede**: do primeiro ao último evento do transcript.
- **modelo**: de cada resultado de ferramenta (ou pedido) até a última resposta do modelo antes do
  próximo. É o tempo pensando e escrevendo.
- **ferramentas**: soma de `tool_use` até `tool_result`. Chamadas em paralelo se sobrepõem, então a
  soma pode passar da parede.
- **segundo plano**: o `tool_result` de um comando com `run_in_background` chega na hora, só com o
  id da tarefa. O tempo dele vai do `tool_use` até a notificação de fim da tarefa, entra nas
  categorias e nas mais lentas com a marca `[2º plano]`, e a soma fica em `segundo_plano_s` no
  `--json`. O agente pode trabalhar enquanto o comando roda: este tempo se sobrepõe ao do modelo e
  ao das outras ferramentas. Sem notificação (servidor que fica no ar, sessão interrompida), a
  chamada aparece nas penduradas como `2º plano sem fim`.
- **categorias**: o comando do Bash é classificado por regex, na ordem: `portão` (`just pronto`,
  `pronto.py`, `pre-commit run`, `make check`, `tox`, `nox`), `testes` (pytest, npm test, go test,
  cargo test...), `lint/tipos`, `git`, `leitura` (grep, cat, sed -n...), `bash (outro)`. As outras
  ferramentas vão pelo nome: Read/Grep/Glob são `leitura`, Edit/Write são `edição`, Agent é
  `subagente`.
- **penduradas**: chamada sem resultado (o agente foi interrompido ou ainda roda) ou que chegou a
  90% do prazo do Bash (`--limiar`). É o sinal de teste pendurado ou hook lento.

Categorias do seu projeto, testadas antes das padrão:

```bash
python $S/mede_agente.py pasta/ \
  --categoria 'navegador=-m navegador|playwright' \
  --categoria 'migração=alembic|manage.py migrate'
```

`--so-categorias` usa só as suas.

## Do sinal à ação

| o que a medida mostra | o que fazer |
|---|---|
| `testes` + `portão` perto da metade do tempo | só os testes do que mudou enquanto itera; portão uma vez (`testes-para-agentes.md`) |
| a mesma chamada de teste repetida muitas vezes | o agente está em laço de conserto: briefing com teto de tempo |
| chamada pendurada perto do prazo em teste de banco | `lock_timeout` e `statement_timeout` nas conexões de teste, `pytest-timeout` |
| chamada pendurada em `git commit` ou `git push` | hook lento: selo do portão no pre-push |
| vários agentes com testes lentos ao mesmo tempo | workers por agente (`PYTEST_WORKERS`) |
| `contexto_max` alto e muitas `imagens_lidas` | texto da captura antes da imagem (`leitura-barata.md`) |
| `contexto_max` alto na tarefa 2 em diante do mesmo agente | agente retomado: tarefa nova vai para agente novo |
| `bytes_de_resultado` alto no Bash | saída sem filtro: `| tail`, `grep`, `-q` |
| `modelo` maior que `ferramentas` com pouca saída | briefing ambíguo; o agente está decidindo o que fazer |
| muitas chamadas `leitura` curtas | mapeamento inline: mande para um subagente de leitura ou use o grafo |

## Números de referência

De um dia com 10 agentes: uns 280 minutos-agente, uns 48% do tempo de ferramenta em teste
(pytest 84 minutos, portão 35). Um agente perdeu uns 45 minutos num teste pendurado num lock de
linha; outro, 10 minutos num pre-push que repetiu a suíte. Esses dois sozinhos eram 20% do total,
e os dois somem com prazo no banco e selo no pre-push.
