# Editar em lote e provar

Quatro ferramentas, quatro perguntas diferentes:

| pergunta | ferramenta |
|---|---|
| preciso trocar texto em vários arquivos, tudo ou nada | `troca.py` |
| mudei só comentário, docstring ou nome de teste? | `mesmo_ast.py` |
| este teste pega mesmo a armadilha que diz pegar? | `muta.py` |
| que linha desta regra nenhuma asserção protege? | `mutacao_ast.py` |

Nos comandos, `S=~/.claude/skills/dev-agentes/scripts`.

## troca.py: trocas em lote, atômicas

```json
[
  {"arquivo": "src/precos.py", "velho": "def calcula(", "novo": "def calcula_total("},
  {"arquivo": "tests/test_precos.py", "velho": "calcula(", "novo": "calcula_total(", "todas": true}
]
```

```bash
python $S/troca.py trocas.json        # ou - para ler do stdin; --base para outra raiz
```

- Cada `velho` tem que aparecer **exatamente uma vez** no arquivo, ou nenhuma troca é gravada.
  Com `"todas": true`, aceita várias ocorrências (e recusa zero).
- Trocas do mesmo arquivo rodam em ordem, cada uma sobre o resultado da anterior.
- Saída: quantas substituições cada arquivo recebeu. Recusa: `nada gravado.` e cada motivo.

**Quando.** Mais de duas ou três trocas, ou trocas em mais de um arquivo que precisam ir juntas.
Uma troca só: a ferramenta de edição. Nunca um heredoc de Python com `replace`: pede permissão,
esconde o diff e não recusa a troca ambígua.

**Dica.** Para um agente aplicar centenas de trocas decididas por outros (limpeza de comentário,
renomeação), gere o JSON e aplique numa passada; o erro de uma troca ambígua aparece antes de
qualquer arquivo mudar.

## mesmo_ast.py: o refactor só mudou texto

```bash
python $S/mesmo_ast.py --ref main              # todos os .py mudados desde main
python $S/mesmo_ast.py --ref main src/ tests/  # só estes caminhos
```

Compara a árvore sintática de cada `.py` mudado contra a versão em `--ref`, ignorando:
comentário, docstring e texto solto, `pass` e `...` sozinhos, e o nome de funções e classes de
teste (`test*`/`Test*` em `tests/` ou `test_*.py`), que são trocados pela posição.

Saída:
- `CÓDIGO arquivo` com a primeira diferença (linha antes e depois): mudou comportamento.
- `DUPLICA arquivo: nome`: um renomeio criou dois testes com o mesmo nome no mesmo corpo (o
  segundo apaga o primeiro em silêncio).
- `RENOMEIA arquivo: velho -> novo`: informativo.
- `REFERÊNCIA caminho:linha`: o nome antigo ainda é citado (doc, outro teste). Registro datado
  (`*-AAAA-MM-DD.md`) não conta; mude com `--registro REGEX`, ou `--registro ''` para desligar.
- `NOVO OU APAGADO`: arquivo sem par para comparar; confira à mão.

Sai com 1 se houver qualquer coisa além de `RENOMEIA`.

**Quando.** Limpeza de comentário e docstring em lote, renomear testes, reformatar: todo PR que
diz "não muda comportamento" prova isso com uma linha, e a revisão fica só no texto.

## muta.py: o teste pega a armadilha

```json
[{"teste": "tests/test_precos.py::test_arredonda_para_cima",
  "arquivo": "src/precos.py", "velho": "math.ceil(", "novo": "round("}]
```

```bash
python $S/muta.py mutacoes.json                       # usa "uv run pytest"
python $S/muta.py mutacoes.json --pytest "python -m pytest"
```

Para cada item: roda o teste no código atual (tem que passar), aplica a mutação com as regras do
`troca.py` (tem que aparecer uma vez), roda de novo (tem que falhar), e devolve o arquivo byte a
byte, mesmo se o pytest levantar ou houver Ctrl-C. Saída `PEGA` com a linha decisiva do erro,
`NÃO PEGA` com o motivo (não passa no código atual, passa mesmo com a mutação, arquivo não voltou)
ou `RECUSADA` (mutação ambígua).

**Quando.** Ao escrever o teste de uma armadilha ("se alguém trocar X por Y, quebra sem avisar"):
a mutação é a troca óbvia e errada, e o `PEGA` é a prova de que o teste protege. Só em teste
rápido: nunca em teste de navegador ou de vários minutos, porque cada item roda o teste duas vezes.
Não mate no meio: espere a rodada terminar, que o arquivo volta sozinho.

## mutacao_ast.py: achar linha desprotegida

```bash
python $S/mutacao_ast.py --alvo src/regra.py=tests/test_regra.py,tests/test_props.py
python $S/mutacao_ast.py                     # alvos de .mutacao.toml ou [tool.mutacao]
python $S/mutacao_ast.py src/regra.py        # só este alvo da config
```

```toml
# .mutacao.toml
[alvos]
"src/regra.py" = ["tests/test_regra.py"]

[equivalentes."src/regra.py"]
"L26: Or -> And" = "com and a string vazia cai no mesmo None mais abaixo"
```

Gera mutantes pela árvore sintática (`>=` vira `>`, `<` vira `<=`, `==` vira `!=`, `and` vira
`or`, tira `not`), um por vez, roda os testes mapeados com `-x` e sem cache de bytecode, e lista
os que sobreviveram. Mutante que sobrevive é linha que dá para quebrar sem a suíte reclamar.
Equivalente é a troca que não muda comportamento observável: registre com o motivo, e ele sai da
contagem de lacunas. Sai com 1 se sobrar lacuna real. O arquivo volta byte a byte no fim.

**Quando.** Sob demanda, em módulo de regra pura (preço, contagem, validação de identificador),
que roda sem banco e é barato de mutar. Módulo com I/O mede o mock, não a regra. Não vai para o
CI: é diagnóstico, e o custo cresce com o número de mutantes. Para provar uma armadilha
específica, `muta.py`; para descobrir onde falta asserção, este.
