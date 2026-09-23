# Permissões: liberar o que só lê

Cada pedido de permissão para o agente até alguém responder. Num lote de agentes, isso é tempo
parado. Liberar de antemão os comandos que só leem corta a maior parte dos pedidos sem abrir mão
de conferir o que escreve.

## O padrão

Em `.claude/settings.json` do projeto (vai para o git e vale para todos) ou em
`.claude/settings.local.json` (só na sua máquina):

```json
{
  "permissions": {
    "allow": [
      "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)",
      "Bash(git grep:*)", "Bash(git blame:*)", "Bash(git rev-parse:*)", "Bash(git worktree list:*)",
      "Bash(gh pr view:*)", "Bash(gh pr checks:*)", "Bash(gh pr diff:*)", "Bash(gh run list:*)",
      "Bash(gh run view:*)", "Bash(gh issue view:*)",
      "Bash(ls:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(wc:*)",
      "Bash(grep:*)", "Bash(rg:*)",
      "Bash(nproc)", "Bash(free:*)", "Bash(df:*)"
    ]
  }
}
```

## O que fica de fora, e por quê

- **Escrita e publicação:** `git push`, `git commit`, `git reset`, `gh pr merge`, `gh pr create`,
  deploy, `docker compose up`, qualquer coisa que mude estado fora da árvore de trabalho. Por
  isso a lista acima libera subcomandos do `git` e do `gh`, e não `Bash(git:*)` ou `Bash(gh:*)`
  inteiros: esses liberariam push, merge e reset junto.
- **`find` e `sed` genéricos:** `find -delete`, `find -exec` e `sed -i` escrevem. Libere a forma
  exata que você usa, se for o caso.
- **`uv run:*`, `just:*`, `npm run:*`, `make:*`:** executam código arbitrário do projeto. Liberar
  poupa muitos pedidos (testes, portão), mas é uma decisão consciente: vale em máquina de
  desenvolvimento sem segredo de produção carregado, não em máquina que tem acesso a deploy.
- **`python -c` e heredoc de Python:** execução arbitrária; não há padrão seguro. É mais um motivo
  para usar os scripts desta skill por caminho fixo, que dá para liberar um a um:
  `"Bash(python ~/.claude/skills/dev-agentes/scripts/pronto.py:*)"`.

## Achar o que liberar

Os pedidos que mais se repetem estão nos transcripts. O `mede_agente.py --json` lista as
ferramentas por agente; para os comandos, procure nos `.jsonl` os `tool_use` de Bash mais comuns
e libere os que só leem.
