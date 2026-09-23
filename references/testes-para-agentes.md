# Testes rodados por agentes

Teste é o maior gasto de tempo de um agente. Em 10 agentes medidos num dia, uns 48% do tempo
de ferramenta foi teste: pytest 84 minutos e o portão 35 minutos, de uns 280 minutos-agente. O
que segue corta esse tempo sem cortar a conferência.

## Conteúdo

1. Iterar com o teste do que mudou
2. Workers por agente
3. Teste de banco não pendura: lock_timeout e statement_timeout
4. pytest-timeout
5. Sem sleep fixo
6. Rede bloqueada
7. Portão uma vez e selo no pre-push
8. Teste de navegador

## 1. Iterar com o teste do que mudou

Enquanto itera, o agente roda o arquivo de teste do módulo mexido, com `-k` quando cabe:
`pytest tests/test_precos.py -k arredonda -q`. A suíte inteira roda uma vez, no portão, no fim.
Rodar tudo a cada mudança multiplica o tempo pelo número de iterações e despeja saída demais no
contexto.

Dica: `pytest --lf` roda só o que falhou na última vez; `-x` para no primeiro erro.

## 2. Workers por agente

`pytest -n auto` usa todos os núcleos. Com três agentes fazendo isso na mesma máquina, são três
vezes mais processos que núcleos, e tudo fica lento ao mesmo tempo. Um pytest que parou com CPU
perto de zero é disputa ou lock, não teste lento.

Deixe o número de workers vir de uma variável, e o briefing diz quanto cada agente usa:

```python
# tests/conftest.py
import os


def pytest_xdist_auto_num_workers(config):
    workers = os.environ.get("PYTEST_WORKERS")
    return int(workers) if workers else None
```

Com isso, `pytest -n auto` respeita `PYTEST_WORKERS=4`, e sem a variável continua usando todos os
núcleos (bom para o CI e para uma pessoa só). Quatro por agente é um bom começo numa máquina de
16 núcleos com três ou quatro agentes.

## 3. Teste de banco não pendura: lock_timeout e statement_timeout

Um agente perdeu uns 45 minutos com testes parados, esperando um lock de linha que outra conexão
do mesmo teste segurava. O Postgres espera um lock para sempre, por padrão. Em teste, qualquer
espera longa é defeito: ponha prazos curtos em toda conexão de teste, e o teste pendurado vira
falha com a mensagem `canceling statement due to lock timeout` em segundos.

SQLAlchemy com asyncpg, para todo engine criado nos testes:

```python
# tests/conftest.py
from sqlalchemy import event
from sqlalchemy.engine import Engine

ESPERA_DO_TESTE = {
    "lock_timeout": "5s",
    "statement_timeout": "30s",
    "idle_in_transaction_session_timeout": "2min",
}


@event.listens_for(Engine, "do_connect")
def _espera_curta(dialeto, registro, cargs, cparams):
    cparams["server_settings"] = {**ESPERA_DO_TESTE, **cparams.get("server_settings", {})}
```

Com psycopg (2 ou 3), o mesmo vai por `options`:

```python
@event.listens_for(Engine, "do_connect")
def _espera_curta(dialeto, registro, cargs, cparams):
    opcoes = " ".join(f"-c {k}={v}" for k, v in ESPERA_DO_TESTE.items())
    cparams["options"] = f"{cparams.get('options', '')} {opcoes}".strip()
```

Sem SQLAlchemy, a variável `PGOPTIONS="-c lock_timeout=5s -c statement_timeout=30s"` no ambiente
do pytest vale para toda conexão libpq (psycopg, psql). asyncpg não lê `PGOPTIONS`: use
`server_settings=` no `connect`.

Migration também merece `SET lock_timeout` no começo: em produção, uma migration presa num lock
bloqueia todo mundo que chega depois dela.

Prove o prazo com um teste: uma conexão faz `SELECT ... FOR UPDATE`, a outra tenta o mesmo e tem
que falhar com lock timeout em menos de um segundo (com o prazo baixado para `200ms` no teste).

## 4. pytest-timeout

A rede de segurança para o que não é banco:

```toml
# pyproject.toml
[tool.pytest.ini_options]
timeout = 120
```

com `pytest-timeout` nas dependências de desenvolvimento. O teste que passa do prazo falha com o
traceback de onde estava parado, em vez de segurar o agente até o prazo da ferramenta dele.
Teste que precisa de mais tempo declara `@pytest.mark.timeout(600)`, à vista.

## 5. Sem sleep fixo

`time.sleep(0.5)` em teste é lento quando a máquina está folgada e falho quando está ocupada.
Espere a condição:

- Dependência lenta falsa: um `threading.Event` que só o código testado dispara. O teste de "isto
  não bloqueia o laço de eventos" fica assim, sem `sleep` e sem limiar de latência: a dependência
  falsa espera o evento, e só o laço livre consegue dispará-lo.
- Serviço subindo: laço com prazo que consulta a condição (`/saude` respondendo), não `sleep 5`.
- Página web: espere um marcador de página quieta (requisições do htmx paradas, fontes e imagens
  carregadas), não `networkidle` mais um tempo fixo.

Não mate processo `sleep` pelo nome: outros serviços da máquina (laços de backup em contêiner)
podem ser donos de um. Filtre pelo PID do pai.

## 6. Rede bloqueada

Nenhum teste fala com serviço externo de verdade: custa dinheiro, vaza dado, falha por acaso, e
pode acontecer em silêncio (um cliente de monitoramento real que mandava eventos para fora sem
nenhuma falha visível). Dependência externa é mock.

`scripts/sem_rede.py` é um plugin do pytest que bloqueia `connect`, `connect_ex` e `getaddrinfo`
para qualquer destino fora do loopback, e faz o teste falhar no teardown mesmo quando o código
engoliu o erro:

```bash
PYTHONPATH=~/.claude/skills/dev-agentes/scripts pytest -p sem_rede
```

ou copie o arquivo para `tests/sem_rede.py` e declare `pytest_plugins = ["tests.sem_rede"]` no
`conftest.py` da raiz. Banco em contêiner com nome próprio (`db`, `postgres`) ou rede privada
entra por `SEM_REDE_LOCAIS=db,172.16.0.0/12`. Essa lista é para serviço local; nunca ponha nela
um host externo.

O navegador que um teste abre é outro processo e não é coberto pelo plugin: lance-o com
`--host-resolver-rules` que só resolve nomes locais.

## 7. Portão uma vez e selo no pre-push

O portão (`pronto.py`) roda o que o CI roda, sem consertar, e mostra só a cauda do que falhou:

```toml
# .pronto.toml (ou [tool.pronto] no pyproject.toml)
passos = [
  "ruff check .",
  "ruff format --check .",
  "pytest -q -n auto -m 'not navegador'",
]
prazo = 900   # segundos por passo; passou, mata o grupo de processos
linhas = 40
```

```bash
python ~/.claude/skills/dev-agentes/scripts/pronto.py
```

Se tudo passa, ele grava `.local/pronto.stamp` com a árvore testada: o hash que o disco teria se
tudo fosse commitado, calculado com uma cópia temporária do índice (o índice de verdade não muda)
e respeitando o `.gitignore`. Se o disco mudou durante a rodada, não grava.

Um agente perdeu 10 minutos num pre-push que rodou a suíte inteira logo depois do portão, na mesma
árvore. O `push_pronto.py` pula os testes só quando o selo, o disco e o commit empurrado são a
mesma árvore; em qualquer outro caso roda o comando e devolve o código dele.

Hook do framework pre-commit:

```yaml
- repo: local
  hooks:
    - id: testes
      name: testes
      entry: python /caminho/para/dev-agentes/scripts/push_pronto.py -- pytest -q
      language: system
      pass_filenames: false
      always_run: true
      stages: [pre-push]
```

Ou o hook do git direto, em `.git/hooks/pre-push` (o git passa as refs no stdin, e o script lê):

```sh
#!/bin/sh
exec python ~/.claude/skills/dev-agentes/scripts/push_pronto.py -- pytest -q
```

O que faz os testes rodarem de novo: commit depois do portão, mudança não commitada, arquivo novo
fora do `.gitignore`, ou empurrar uma ref que não é a árvore do disco. Rodar o portão com mudança
pendente e commitar depois vale: a árvore commitada é a que passou.

Teste de hook que usa git num diretório temporário precisa de ambiente limpo: o git exporta
`GIT_DIR` e `GIT_INDEX_FILE` para o hook, e um `git init` num `tmp_path` herdando isso escreve no
repositório de verdade. Apague toda variável `GIT_*` no fixture.

## 8. Teste de navegador

- Um teste por tela que abre a página uma vez e troca o tamanho da janela, em vez de abrir uma vez
  por largura.
- Espere o marcador de página quieta, não `networkidle` mais tempo fixo.
- Roda uma vez, para verificar. Nunca em laço, nunca com mutação.

Numa suíte, só tirar as esperas fixas e as aberturas repetidas levou a rodada com 4 workers de
295 para 77 segundos.
