# Medir o banco com pg_stat_statements

`pg_stat_statements` guarda, por consulta normalizada (literais trocados por `$1`, `$2`), quantas
vezes rodou, quanto tempo levou e quantos blocos leu. É a forma mais barata de saber onde o banco
passa o tempo, sem adivinhar pela leitura do código.

Medir é opcional e sempre com o sim da pessoa. O script desta skill só lê.

## 1. Antes de conectar: o sim

O agente diz, com todas as letras, antes de rodar qualquer coisa:

- **qual banco**: dev ou prod, e o nome dele;
- **por qual conexão**: túnel SSH, DSN, usuário (sem mostrar senha);
- **o que vai fazer**: só ler estatísticas agregadas, sessão só de leitura, com prazo por comando.

E espera um sim explícito. Dois passos são sins separados, e quem roda é um humano:

- **Ligar a extensão**: `shared_preload_libraries = 'pg_stat_statements'` no `postgresql.conf`
  (somando às bibliotecas que já estão lá) e **reiniciar o Postgres**; depois
  `CREATE EXTENSION pg_stat_statements;` no banco. Reinício em produção é janela de manutenção.
- **Zerar as estatísticas**: `SELECT pg_stat_statements_reset();` apaga a janela acumulada, que
  pode ser a única foto de semanas de uso real.

O `pg_top.py` nunca roda esses comandos: quando falta algo, ele imprime o que falta, marcado como
escrita ou reinício.

## 2. Dev ou prod

**Números de dev enganam.** Tabela pequena cabe inteira na memória: tudo é acerto de cache, varredura
sequencial é mais rápida que índice, e a consulta que em produção lê um milhão de linhas lê cem.
O plano muda com o volume. Dev só vale com volume parecido com o de produção (uma cópia
anonimizada, ou dados gerados na mesma ordem de grandeza) e depois de aquecer o cache com a carga.

**Prod mostra a verdade, com cuidado.** Só leitura agregada, pelo usuário de menor privilégio que
lê `pg_stat_statements` (o papel `pg_read_all_stats`), com `statement_timeout` curto. Nunca
`EXPLAIN ANALYZE` em prod sem outro sim: ele executa a consulta.

## 3. O fluxo

1. Ligar a extensão e reiniciar (humano, uma vez).
2. Zerar a janela (humano, com sim).
3. Rodar a carga: o teste de carga, a suíte de perfil, ou um período conhecido de uso real.
4. Ler o topo:
   ```bash
   PGPASSWORD=... python ~/.claude/skills/dev-agentes/scripts/pg_top.py \
     --alvo dev --dsn "postgresql://leitor@localhost:5432/app" --confirmo
   ```
   `--ordem total --ordem media` para escolher os rankings, `--limite`, `--largura` do texto,
   `--prazo 5s`. A DSN também vem de `PG_TOP_DSN`. Deixe a senha no `~/.pgpass` ou em `PGPASSWORD`,
   não na DSN, que aparece na lista de processos.
5. Consertar a pior consulta (índice, N+1, paginação, cache).
6. Zerar de novo (sim de novo), rodar **a mesma carga na mesma janela** e ler de novo.

Antes e depois só se comparam com carga e janela iguais. Comparar o total de uma semana com o de
uma hora não diz nada.

O script usa o `psql` do PATH, com `-X` (sem `.psqlrc`), `PGOPTIONS` com
`default_transaction_read_only=on` e `statement_timeout`, e `PGAPPNAME=pg_top-<alvo>` para a sessão
aparecer identificada em `pg_stat_activity`. Todo SQL enviado passa por uma checagem que recusa o
que não começa por `SELECT`, `SHOW` ou `WITH`, ou que cita escrita. Precisa de Postgres 13 ou
mais novo (colunas `total_exec_time` e `mean_exec_time`).

## 4. Como ler as colunas

| coluna | o que diz | o que procurar |
|---|---|---|
| `calls` | quantas vezes rodou na janela | alto com `linhas_por_chamada` 1: N+1, laço que consulta item a item |
| `total_ms` | tempo somado de todas as chamadas | onde o banco passa o dia; o topo daqui é o que mais rende consertar |
| `media_ms` | tempo por chamada | a consulta lenta em si; alto com poucas chamadas pode ser relatório, e tudo bem |
| `rows` e `linhas_por_chamada` | linhas devolvidas | milhares por chamada numa tela que mostra 20: falta paginação ou filtro |
| `hit_pct` | blocos achados no cache sobre blocos lidos | abaixo de uns 95% numa consulta frequente: lê disco, falta índice ou memória |
| `consulta` | texto normalizado, cortado | o esquema aparece aqui |

Rankings que o script mostra:

- **total**: onde o tempo vai. Uma consulta de 2 ms chamada um milhão de vezes ganha de uma de
  2 segundos chamada dez vezes.
- **media**: a consulta lenta individual (a que o usuário sente numa tela).
- **chamadas**: N+1 e laços.
- **linhas**: consulta que traz demais.
- **cache**: menor acerto de cache, que lê disco.

O bloco de contexto (`pg_stat_database`) dá o acerto de cache do banco todo e desde quando as
estatísticas contam.

## 5. O que a saída revela

O texto normalizado mostra nomes de tabela e coluna, e, raramente, valores literais (consulta
montada com literal que o normalizador não trocou, ou comentário dentro da consulta). Trate a saída
como dado interno: não cole em issue pública, chat aberto ou PR de repositório público. Resuma
("a consulta de listagem de pedidos por cliente: 40% do tempo total, N+1") em vez de colar o texto.
