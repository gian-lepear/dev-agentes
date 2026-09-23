# Briefing de agente

O briefing é o único lugar onde dá para economizar antes de gastar. Um subagente não sabe o que
você sabe, não vê a conversa e segue o texto ao pé da letra: o que o briefing deixa aberto ele
preenche caçando. Cada regra abaixo tem o porquê, com um caso medido, e o jeito de aplicar.

## Conteúdo

1. Escopo fechado e relatório curto
2. Orçamento escrito não segura o agente
3. Tarefa nova, agente novo
4. Teto de tempo por conferência
5. Testes: só o que mudou, portão no fim
6. Nada pago sem pedido
7. CI: rascunho e um push só
8. Esperar sem `sleep`
9. Editar sem heredoc
10. Modelo e esforço
11. Bloco para colar no briefing

## 1. Escopo fechado e relatório curto

**Regra.** Liste exatamente o que entra. Diga o que fazer com o que sobra: vai como pendência no
relatório ou no PR, sem conserto. Peça relatório curto e saída de comando filtrada.

**Por quê.** Um agente recebeu a meta "zero alvos de toque pequenos em criar e revisar"; o teste
que ele mesmo escreveu cobrava zero em todas as telas, e ele saiu caçando tela por tela, com um
inventário inteiro de 68 KB entrando no contexto a cada leitura. Chegou a 168 mil tokens de
contexto e 66 chamadas sem entregar nada, e foi cancelado.

**Como.**
- Escreva "entra: A, B, C. Não entra: o resto. Achou mais? Liste no relatório, não conserte."
- "Relatório em até 15 linhas: o que mudou, o que ficou pendente, como conferir."
- "Toda saída de comando passa por `| tail -n 40` ou `grep`; arquivo grande se lê por trecho."

## 2. Orçamento escrito não segura o agente

**Regra.** Orçamento no texto ("umas 35 chamadas") é desejo, não freio. Em tarefa com código novo
e testes, meça o custo no meio e pare ou redirecione quando passar do combinado.

**Por quê.** Um briefing pediu cerca de 35 chamadas; o agente fez 209, com 266 mil tokens de
contexto no fim.

**Como.** `python $S/mede_agente.py <transcript do agente>` enquanto ele roda (o transcript é
gravado ao vivo). Se o contexto passou de uns 150 mil ou as chamadas passaram do dobro do
combinado, mande parar e entregar o que tem.

## 3. Tarefa nova, agente novo

**Regra.** Tarefa independente vai para agente novo, com um briefing próprio (de preferência um
arquivo de briefing reaproveitável). Retomar o mesmo agente só para corrigir o mesmo entregável.

**Por quê.** Retomar um agente carrega o histórico inteiro dele em toda requisição. Um agente de
revisão por capturas foi retomado para cinco tarefas diferentes: a primeira começou com 39 mil
tokens de contexto, as seguintes já começavam com 340 mil a 520 mil, porque 192 leituras de
imagem de página inteira ficaram no histórico. Uns dois terços da entrada das tarefas 2 a 5 foram
histórico inútil. Imagem é o item mais caro do contexto e não sai dele.

**Como.** Guarde o briefing num arquivo (`briefings/revisao.md`) e passe o caminho ao agente
novo. Tentar de novo depois de uma falha também é agente novo, com o briefing corrigido, e não
"tente de novo" para o mesmo.

Um agente especializado, com poucas ferramentas e sem o arquivo de instruções do projeto, tem
piso de contexto bem menor que o agente genérico (numa medição, 5 mil contra 37 mil tokens). Para
tarefa repetida, vale definir um. Tarefa pequena não barateia: o piso fixo do agente domina.

## 4. Teto de tempo por conferência

**Regra.** Nenhuma conferência lenta passa de 10 minutos. Mutação só em teste rápido. Teste de
navegador roda uma vez, para verificar, nunca em laço.

**Por quê.** Um agente ficou uns 30 minutos preso repetindo a mesma prova de mutação num teste de
navegador: cada rodada levava uns 10 minutos, porque o navegador subia várias vezes.

**Como.** Escreva o teto no briefing. Se a conferência vai passar dele, corte o escopo (`-k`,
um arquivo, uma tela) em vez de esperar. Se um agente já passou do teto, deixe a rodada atual
terminar antes de parar: o `muta.py` restaura o arquivo ao sair, e matar no meio pode deixar a
mutação no código.

## 5. Testes: só o que mudou, portão no fim

**Regra.** Enquanto itera, rode só os testes dos arquivos que mexeu. O portão completo roda uma
vez, no fim. Com vários agentes na mesma máquina, limite os workers do xdist por agente.

**Por quê.** Em 10 agentes medidos num dia, teste foi uns 48% do tempo de ferramenta: pytest
84 minutos e o portão 35 minutos, de uns 280 minutos-agente. Um agente perdeu uns 45 minutos num
teste pendurado num lock de linha do Postgres, e outro perdeu 10 minutos num pre-push que rodou a
suíte inteira de novo logo depois do portão.

**Como.** No briefing: "iterando, `pytest tests/test_x.py -k ...`; no fim, o portão uma vez;
workers do xdist por `PYTEST_WORKERS=4`". O resto (timeouts de banco, selo do pre-push) está em
`testes-para-agentes.md`.

## 6. Nada pago sem pedido

**Regra.** Chamada paga de IA, ou qualquer serviço externo real, só com pedido explícito da
pessoa, a cada vez, com a quantidade de chamadas e o custo estimado antes. O padrão do
desenvolvimento é sem serviço real: falsos e mocks.

**Por quê.** Medições "rapidinhas" com a API real somam, e a pessoa não viu o custo antes. Um
teste que deixava um cliente real de monitoramento ligado mandava eventos para fora sem nenhuma
falha visível.

**Como.** Guarde as chaves pagas num arquivo de ambiente separado que ninguém carrega por padrão
(`.env.pago`), carregue só na rodada autorizada. Se já existe número medido, use o número. Na
suíte, bloqueie a rede (`sem_rede.py`) para que o vazamento vire falha.

## 7. CI: rascunho e um push só

**Regra.** Agente abre PR como rascunho (`gh pr create --draft`), roda o portão local, junta os
commits e dá push uma vez no fim. `gh pr ready` só quando for mergear. Não propor job novo, matriz
ou teste lento no CI sem necessidade.

**Por quê.** Com vários agentes abrindo PR e dando push várias vezes, a cota mensal de minutos de
CI acabou na metade do mês. Cada push roda o CI, que é cancelado pelo push seguinte, e o minuto é
cobrado mesmo assim.

**Como.** Ver `paralelizar.md` para o CI por lote e para conferir que o CI certo rodou.

## 8. Esperar sem `sleep`

**Regra.** CI: `gh pr checks N --watch` em segundo plano. Serviço subindo: ferramenta de monitor
com condição de parada. Portão antes de PR: `pronto.py`, não lint, tipos e testes soltos.

**Por quê.** Sessões acumulavam dezenas de `sleep N; curl` e `until curl .../health`, cada
tentativa uma ida e volta ao modelo, e perto de mil chamadas separadas de lint, tipos e testes,
cada uma despejando a saída inteira no contexto.

## 9. Editar sem heredoc

**Regra.** Não editar arquivo com `python - <<EOF ... replace ... write_text`. Uma troca: a
ferramenta de edição. Muitas trocas em vários arquivos: `troca.py` com um JSON.

**Por quê.** Foram centenas de heredocs assim numa quinzena. Todo heredoc de Python pede
permissão (liberar é liberar execução arbitrária), quem acompanha não vê o diff, e o mesmo
`assert count == 1` é reescrito a cada vez.

## 10. Modelo e esforço

**Regra.** Tarefa mecânica (renomear, aplicar lista de trocas, rodar e resumir) vai para modelo
menor. Não troque o modelo do agente para um mais caro sem a pessoa pedir.

**Como.** Se a ferramenta de agentes não deixa mudar o esforço por chamada, ele vem da definição
do agente; defina um agente próprio para a tarefa recorrente.

## 11. Bloco para colar no briefing

```text
Escopo: <lista fechada>. O que sobrar vai como pendência no relatório, sem conserto.
Testes: enquanto itera, só os testes dos arquivos que mexer (pytest caminho -k caso).
No fim, o portão uma vez: python ~/.claude/skills/dev-agentes/scripts/pronto.py.
Teste lento ou de navegador roda uma vez. Nenhuma conferência passa de 10 minutos;
se for passar, corte o escopo. Mutação (muta.py) só em teste rápido.
Workers do xdist: no máximo 4 (PYTEST_WORKERS=4).
Nada de IA paga nem serviço externo real. Não carregue arquivo de chave paga.
Esperar: gh pr checks --watch ou monitor com condição, nunca sleep em laço.
Editar: ferramenta de edição; lote com troca.py. Sem heredoc de Python.
PR em rascunho, um push só no fim. Saída de comando filtrada (| tail -n 40).
Relatório final: até 15 linhas, com o que mudou, o que ficou pendente e como conferir.
```
