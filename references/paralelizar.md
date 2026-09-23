# Paralelizar agentes

Vários agentes ao mesmo tempo só rendem se não pisarem um no outro: no arquivo, no git, na CPU,
no banco e no CI.

## 1. Dividir o trabalho

- **Por arquivo, não por assunto.** Dois agentes no mesmo arquivo viram conflito de merge, e
  quem resolve é você. Antes de soltar o lote, liste os arquivos que cada tarefa vai tocar (o grafo
  de conhecimento ou um subagente de leitura respondem rápido) e junte na mesma tarefa o que
  compartilha arquivo.
- **Arquivos quentes** (o `conftest.py`, o módulo de configuração, o registro de rotas, a
  migration mais nova) ficam com uma tarefa só, ou com a última do lote.
- **Migrations em paralelo** criam duas cabeças. Uma tarefa por lote mexe no esquema, ou a
  segunda refaz a migration em cima da primeira depois do merge.
- Tarefa pequena demais não compensa: o piso de contexto de cada agente é fixo.

## 2. Uma worktree por agente

```bash
git fetch origin
git worktree add ../<projeto>-<assunto> -b <branch> origin/main
```

- **Sempre de um ponto explícito** (`origin/main`). O estado do git no começo da conversa é uma
  foto: outra sessão pode ter trocado a branch do diretório principal depois dela, e um
  `git switch -c` sai do HEAD dela e leva os commits dela junto.
- **Nunca duas sessões no mesmo diretório.** `git checkout` carrega a árvore suja para a branch
  nova sem avisar quando não há conflito de conteúdo; as mudanças de uma sessão aparecem no commit
  da outra. Sintoma: `git status --short` mostra só `??` enquanto `git diff --stat HEAD` mostra
  arquivos modificados, ou `git branch --show-current` responde uma branch que não é a sua.
- **Fora de pastas ignoradas.** Worktree dentro de `.claude/` ou de outra pasta do `.gitignore`
  deixa ferramentas que respeitam ignore (alguns verificadores de tipo) cegas: dizem "0 errors"
  sem ler nada. Crie ao lado do repositório.
- **Não mova a worktree** depois de criar o ambiente virtual: os executáveis guardam o caminho
  antigo. Se mover, recrie o ambiente.
- Antes de todo push: `git log --oneline origin/main..HEAD` mostra só os seus commits?

## 3. Recursos por agente

- **CPU:** workers do xdist por variável (`PYTEST_WORKERS=4`), nunca `-n auto` em todos.
- **Banco:** um banco (ou esquema, ou prefixo) por agente. Teste que clona um banco modelo por
  worker é barato; um Postgres de teste compartilhado com bancos separados evita subir contêiner a
  cada rodada.
- **Portas:** cada agente que sobe servidor usa porta livre (`0` e ler a escolhida), nunca a porta
  fixa do projeto.
- **Matar processo pelo PID**, nunca `pkill -f padrão`: o padrão casa com a própria linha de
  comando da shell e com processos de outros agentes.

## 4. CI por lote

Cada push roda o CI; o push seguinte cancela o anterior, e o minuto é cobrado mesmo assim. Com
vários agentes dando push várias vezes, a cota mensal de uma conta acabou na metade do mês.

- Agentes abrem PR em rascunho (`gh pr create --draft`), rodam o portão local e dão push uma vez.
- Mergeie em ordem: primeiro o que outros dependem (migration, fixture compartilhada), depois o
  resto. Depois de cada merge, os PRs seguintes precisam de rebase se tocam os mesmos arquivos; o
  agente dono do PR faz o rebase, não outro.
- Se o CI só roda em PR pronto, marque `gh pr ready` quando for mergear, não antes.
- Em lote pequeno de mudanças independentes, um PR só com um commit por tarefa gasta um CI em vez
  de vários.

## 5. Esperar o CI certo

`gh pr checks N --watch` espera as checagens da última execução, mas a última execução pode não
ser a que você acha:

- **PR em rascunho:** workflows com `if: github.event.pull_request.draft == false` são pulados; a
  checagem aparece como "skipped", e `--watch` volta verde sem ter testado nada.
- **`ready_for_review`:** só dispara se o workflow escuta esse tipo de evento (`on: pull_request:
  types: [opened, synchronize, reopened, ready_for_review]`). O padrão não inclui; tirar do
  rascunho pode não rodar nada.
- **Solução:** confira o commit da execução (`gh run list --branch <branch> --limit 3` e compare
  o `headSha` com `git rev-parse HEAD`). Se não rodou, empurre um commit vazio:
  `git commit --allow-empty -m "roda o CI" && git push`.
- Espere em segundo plano (`gh pr checks N --watch` com a ferramenta de segundo plano, ou uma
  ferramenta de monitor), nunca com `sleep` em laço.

## 6. Coordenação

- Um arquivo de briefing por tarefa, com a lista fechada de arquivos que ela pode tocar.
- O coordenador não retoma um agente para tarefa nova: agente novo com briefing novo.
- Relatório de cada agente curto e no mesmo formato, para o coordenador juntar sem reler tudo.
- Meça o lote no fim (`mede_agente.py pasta/`) e ajuste o próximo briefing pelo que a medida
  mostrou.
