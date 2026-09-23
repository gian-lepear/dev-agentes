---
name: dev-agentes
description: "Acelera agentes de código e fluxos com vários agentes no desenvolvimento: menos tokens, testes mais rápidos, edição em lote segura, refactor provado e medição de onde o tempo do agente vai. Use SEMPRE que for escrever o briefing de um subagente ou de um workflow, delegar trabalho a agentes em paralelo (worktrees, ordem de merge, CI por lote), rodar testes a partir de um agente (suíte lenta, teste pendurado em lock de banco, pytest-xdist disputando CPU, pre-push que roda a suíte de novo), trocar texto em muitos arquivos de uma vez, provar que um refactor só mudou nome ou texto, provar que um teste pega a armadilha (mutação), medir custo, tokens ou tempo de um subagente pelo transcript, ou medir consultas do Postgres com pg_stat_statements. Também quando a pessoa reclama que os agentes estão lentos, caros ou travados, mesmo sem dizer 'skill'. Scripts prontos em Python puro: troca, mesmo_ast, muta, mutacao_ast, mede_agente, pronto, push_pronto, sem_rede, pg_top."
---

# /dev-agentes

Checklist para deixar agentes de código mais rápidos e mais baratos. Cada seção diz o que
fazer, o comando exato e para onde ir quando precisar de profundidade. As regras vieram de
medição em sessões reais com vários agentes; os números estão nas referências.

Os scripts são Python 3.12+ só com a biblioteca padrão e não importam nada do projeto. Nos
comandos abaixo, `S=~/.claude/skills/dev-agentes/scripts` (ajuste se a skill estiver em outro
lugar). Todos têm `--help` em português.

## 1. Antes de delegar: o briefing

Um briefing aberto é o jeito mais caro de usar um agente. Leia `references/briefing-de-agente.md`
na primeira vez; depois, confira esta lista em todo briefing de subagente ou workflow:

- **Escopo fechado.** Liste exatamente o que entra e diga o que fazer com o que sobra (vira
  pendência no relatório ou no PR, sem conserto). Meta aberta ("zero X em todas as telas") faz o
  agente caçar sem fim.
- **Relatório curto** e saída de comando sempre filtrada (`| tail -n 40`, `grep`).
- **Testes:** enquanto itera, só os testes dos arquivos mexidos; o portão (`pronto.py`) uma vez no
  fim; teste de navegador ou lento roda uma vez, para conferir, nunca em laço.
- **Teto de tempo:** nenhuma conferência lenta passa de 10 minutos. Mutação só em teste rápido.
- **Nada pago sem pedido:** IA paga ou serviço externo real só com o sim explícito da pessoa e o
  custo estimado antes. O padrão é falso ou mock.
- **CI:** PR em rascunho, um push só no fim, pronto para revisão só quando for mergear.
- **Esperar sem `sleep`:** `gh pr checks N --watch` em segundo plano, ou uma ferramenta de
  monitor com condição de parada.
- **Editar sem heredoc de Python:** uma troca é a ferramenta de edição; muitas são o `troca.py`.
- **Tarefa nova vai para agente novo** com briefing próprio. Retomar o mesmo agente só para
  corrigir o mesmo entregável: retomado, ele relê o histórico inteiro a cada chamada.
- **Orçamento escrito não segura o agente.** Em tarefa grande, meça no meio (seção 6) e pare ou
  redirecione quando passar do combinado.

## 2. Rodar testes a partir de um agente

Teste é quase metade do tempo de ferramenta dos agentes. Detalhes e trechos de código em
`references/testes-para-agentes.md`.

- Iterando: `pytest tests/test_x.py -k caso`, nunca a suíte inteira a cada mudança.
- Vários agentes na mesma máquina: limite os workers do xdist por agente (4 é um bom começo)
  por variável de ambiente, em vez de `-n auto` em todos.
- Teste que toca banco: `lock_timeout` e `statement_timeout` curtos em toda conexão de teste,
  e `pytest-timeout` na suíte. Teste pendurado vira falha em segundos, não em 45 minutos.
- Sem `sleep` fixo em teste: espere a condição (evento, marcador de página quieta).
- Rede bloqueada fora do loopback: `pytest -p sem_rede` com `PYTHONPATH=$S`, ou copie
  `$S/sem_rede.py` para `tests/` e declare `pytest_plugins = ["tests.sem_rede"]`.
- Chamada que para com CPU perto de zero é disputa ou lock, não teste lento: investigue, não
  espere.

## 3. O portão antes de commit ou PR

```bash
python $S/pronto.py "ruff check ." "ruff format --check ." "pytest -q"   # ou passos no .pronto.toml
```

Roda o que o CI roda, sem consertar nada, e mostra só a cauda do que falhou (`--linhas`,
`--prazo` por passo, `--para` no primeiro erro). Se tudo passa e o disco não mudou durante a
rodada, grava `.local/pronto.stamp` com a árvore testada (ponha `.local/` no `.gitignore`).

O pre-push lê esse selo e não roda a suíte de novo quando a árvore empurrada é a mesma:

```bash
python $S/push_pronto.py -- pytest -q     # no hook pre-push, ou como hook do pre-commit
```

Sai com 0 sem rodar nada se o selo, o disco e o commit empurrado são a mesma árvore; senão roda o
comando e devolve o código dele. Configuração de hook em `references/testes-para-agentes.md`.

## 4. Editar em lote e provar o refactor

Quando usar cada um: `references/edicao-e-prova.md`.

- **Muitas trocas, tudo ou nada:** `python $S/troca.py trocas.json` com
  `[{"arquivo", "velho", "novo", "todas"?}]`. Recusa se `velho` não aparece exatamente uma vez e,
  com qualquer recusa, não grava nada.
- **Provar que só nome ou texto mudou:** `python $S/mesmo_ast.py --ref main` compara as árvores
  sintáticas sem comentário, docstring e nome de teste, e acusa referência órfã ao nome antigo.
- **Provar que um teste pega a armadilha:** `python $S/muta.py mutacoes.json` com
  `[{teste, arquivo, velho, novo}]`: passa, falha com a mutação, passa de novo, arquivo devolvido
  byte a byte. `--pytest "python -m pytest"` se o projeto não usa uv.
- **Achar linha de regra que nenhuma asserção protege:** `python $S/mutacao_ast.py --alvo
  src/regra.py=tests/test_regra.py`. Diagnóstico sob demanda em módulo de regra pura, fora do CI.

## 5. Ler barato

Detalhes em `references/leitura-barata.md` e, para cortar pedido de permissão,
`references/permissoes.md`.

- Pergunta estrutural ("quem chama X", "o que quebra se mudar Y") vai primeiro ao grafo de
  conhecimento do repositório, se houver; pergunta pontual vai direto ao arquivo ou ao `grep`.
- Mapeamento amplo vai para um subagente de leitura com saída comprimida.
- Tela: leia o texto e o inventário da captura antes de abrir PNG; abra só a imagem que o diff
  apontou. Antes de capturar, confira se a base de capturas já existe.

## 6. Medir onde o agente gasta

```bash
python $S/mede_agente.py ~/.claude/projects/<projeto>/<sessao>/subagents/   # pasta ou .jsonl
```

Dá tokens, contexto máximo, imagens lidas e custo estimado por agente, e o tempo: parede,
modelo pensando, ferramentas por categoria (testes, portão, leitura, git, edição), as chamadas
mais lentas e as penduradas perto do prazo. Categorias próprias com `--categoria
'navegador=playwright|-m navegador'`. Como ler e o que fazer com cada sinal:
`references/medir-agentes.md`.

## 7. Paralelizar agentes

Detalhes em `references/paralelizar.md`.

- Um agente por worktree, fora de pastas que ferramentas ignoram (`.claude/`, pastas ocultas).
  Worktree nova sempre a partir de ponto explícito (`origin/main`), nunca do HEAD de outra sessão.
- Divida por arquivo, não por assunto: dois agentes no mesmo arquivo viram conflito.
- Banco, porta e diretório temporário próprios por agente.
- Um CI por lote: PRs em rascunho, merge em ordem, e confira que o CI que você espera rodou de
  fato (rascunho pula; `ready_for_review` pode não disparar; um commit vazio resolve).

## 8. Medir o banco (só com o sim da pessoa)

`pg_stat_statements` mostra quais consultas custam mais. Leia `references/medir-banco.md` antes.

1. Diga à pessoa, com todas as letras: qual banco (dev ou prod), por qual conexão (túnel, DSN) e
   que só vai ler estatísticas. Espere o sim.
2. Ligar a extensão (pede `shared_preload_libraries` e reinício do banco) e zerar as estatísticas
   são sins separados, e quem roda é um humano: o script só imprime esses comandos.
3. Prefira dev com volume de dados parecido com o de produção. Em prod, só leitura agregada.
4. `python $S/pg_top.py --alvo dev --dsn "$DSN" --confirmo` (usa o `psql` do PATH, sessão só de
   leitura e com `statement_timeout`).
5. Meça antes e depois da mudança com a mesma carga e a mesma janela.

A saída tem texto de consulta: pode revelar o esquema e, raramente, valores. Não cole em lugar
público.

## Referências

| arquivo | quando ler |
|---|---|
| `references/briefing-de-agente.md` | antes de escrever o primeiro briefing; tem o bloco para colar |
| `references/testes-para-agentes.md` | suíte lenta, teste pendurado, xdist, pre-push, rede |
| `references/edicao-e-prova.md` | troca em lote, refactor provado, mutação manual e automática |
| `references/medir-agentes.md` | ler a saída do `mede_agente.py` e agir |
| `references/paralelizar.md` | vários agentes, worktrees, ordem de merge, CI |
| `references/leitura-barata.md` | grafo, subagente de leitura, capturas de tela |
| `references/permissoes.md` | lista de comandos só de leitura liberados |
| `references/medir-banco.md` | pg_stat_statements, do sim ao antes e depois |
