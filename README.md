# dev-agentes

Uma skill do [Claude Code](https://claude.com/claude-code) para deixar agentes de código mais
rápidos e mais baratos: menos tokens, testes que não penduram, edição em lote segura, refactor
provado, medição de onde o tempo do agente vai e regras de briefing para subagentes e fluxos com
vários agentes.

As regras vieram de medição em sessões reais. Num dia com 10 agentes, uns 48% do tempo de
ferramenta foi teste; um agente perdeu uns 45 minutos num teste pendurado num lock de banco; um
pre-push repetiu a suíte que o portão tinha acabado de rodar; agentes em paralelo disputavam a
CPU com `pytest -n auto`; retomar um subagente para tarefa nova custou o histórico inteiro dele
em cada chamada. Cada um desses virou uma regra e, quando dava, um script.

## Instalar

Clone na pasta de skills do Claude Code:

```bash
git clone https://github.com/<usuario>/dev-agentes ~/.claude/skills/dev-agentes
```

Ou só para um projeto:

```bash
git clone https://github.com/<usuario>/dev-agentes .claude/skills/dev-agentes
```

Com Nix, como input sem flake, e ligado em `~/.claude/skills/dev-agentes` pelo seu home-manager:

```nix
inputs.dev-agentes = {
  url = "github:<usuario>/dev-agentes";
  flake = false;
};

# home-manager
home.file.".claude/skills/dev-agentes".source = inputs.dev-agentes;
```

## Usar

Chame `/dev-agentes`, ou deixe o Claude usar sozinho quando for escrever briefing de subagente,
rodar testes de um agente, trocar texto em vários arquivos, provar um refactor, medir um agente
ou paralelizar trabalho.

Os scripts rodam direto, sem instalar nada (Python 3.12+, só biblioteca padrão; o `pg_top.py`
chama o `psql` do PATH):

| script | faz |
|---|---|
| `scripts/troca.py` | trocas de texto em vários arquivos, tudo ou nada; recusa ocorrência ambígua |
| `scripts/mesmo_ast.py` | prova, pela árvore sintática, que só comentário, docstring e nome de teste mudaram desde uma ref |
| `scripts/muta.py` | prova que um teste pega a armadilha: passa, falha com a mutação, passa de novo |
| `scripts/mutacao_ast.py` | mutação automática em módulo de regra pura; lista a linha que nenhuma asserção protege |
| `scripts/mede_agente.py` | tokens, custo e tempo de agentes pelo transcript JSONL, com o tempo por categoria e as chamadas penduradas |
| `scripts/pronto.py` | portão antes de PR: roda os passos do CI, mostra só a falha, grava o selo da árvore testada |
| `scripts/push_pronto.py` | pre-push que pula os testes quando a árvore empurrada já passou no portão |
| `scripts/sem_rede.py` | plugin do pytest que bloqueia rede fora do loopback |
| `scripts/pg_top.py` | topo do `pg_stat_statements`, só leitura, com trava de confirmação |

Todos têm `--help`.

## Estrutura

- `SKILL.md`: o checklist por situação, com os comandos.
- `references/`: briefing de agente, testes para agentes, edição e prova, medir agentes,
  paralelizar, leitura barata, permissões e medir o banco.
- `scripts/`: as ferramentas acima.
- `tests/`: testes dos scripts (`uv run --with pytest pytest`).
- `evals/evals.json`: pedidos de teste para conferir se a skill dispara e ajuda.

## Desenvolver

```bash
uv run --with pytest pytest
uvx ruff check . && uvx ruff format --check .
```

## Licença

MIT.
