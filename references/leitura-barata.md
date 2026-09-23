# Ler barato

Tudo que o agente lê fica no contexto até o fim e é relido em toda requisição seguinte. Ler menos
e ler texto em vez de imagem é a economia que mais rende.

## 1. Grafo de conhecimento primeiro, para pergunta estrutural

Se o repositório tem um grafo de conhecimento do código (gerado por uma ferramenta de extração
por AST, por exemplo), ele responde bem à pergunta **ampla e estrutural** e mal à pontual:

| vale consultar o grafo | vá direto ao arquivo ou ao grep |
|---|---|
| "quem chama `confere_saldo`?" | "o que a linha 412 faz?" |
| "o que quebra se eu mudar `Opcoes`?" | "qual o valor de `TENTATIVAS`?" |
| "quais módulos falam com o banco?" | ler uma função já localizada |
| "onde mora a regra de X?", sem saber o arquivo | conferir se um teste passa |

Regra prática: se a resposta cabe num `grep` de um termo que você já conhece, use `grep`. Se
precisa descobrir o vocabulário antes de procurar, use o grafo.

Cuidados: grafo desatualizado responde com confiança sobre código que mudou; atualize ao fechar
cada PR. Extração por AST não enxerga template, configuração nem imagem: "ninguém usa isto" dito
pelo grafo não vale para esses arquivos.

## 2. Subagente de leitura com saída comprimida

Mapeamento amplo ("liste os usos de Z", "mapeie este diretório") feito na conversa principal
enche o contexto dela com dezenas de arquivos. Mande para um subagente só de leitura que devolve
`arquivo:linha` e uma frase por achado. A conversa principal guarda a conclusão, não a leitura.

Leitura direta fica para quando você já sabe o trecho.

## 3. Saída de comando filtrada

- `pytest -q`, `| tail -n 40`, `grep -n padrão`, `sed -n '120,160p' arquivo`.
- Um portão que mostra só a cauda do que falhou (`pronto.py`) em vez de quatro comandos soltos.
- JSON grande: `jq` com o campo que interessa, não o arquivo inteiro.

## 4. Tela: texto antes de imagem

Uma captura de página inteira custa milhares de tokens e nunca sai do contexto. Para revisar tela:

1. **Veja se a base de capturas já existe** antes de capturar. Mantenha uma base oficial,
   capturada a partir da branch principal, com um manifesto por tela (rota, commit, hash de cada
   imagem). Uma sessão que recapturou tudo sem olhar gastou minutos refazendo o que existia.
2. **Capture só o que o trabalho mudou**, numa pasta da tarefa (`antes/` e `depois/`), com datas
   congeladas e animação parada, para o hash comparar.
3. **Grave o texto de cada tela junto** (o texto visível, e um inventário de elementos com
   tamanho e posição).
4. **Compare por texto:** um relatório que pareia tela e largura e diz o que é igual byte a byte,
   o que mudou só no pixel e o que mudou no texto custou uns 600 tokens contra uns 23 mil das
   imagens.
5. **Abra só a imagem que o relatório apontou.** Para crítica visual de verdade, abra as imagens
   numa rodada só, em paralelo, e use o inventário para confirmar medidas.

Numa medição, pôr o texto da página e o inventário antes da imagem, para crítica visual, deixou a
revisão 25 a 30% mais cara e pior: para crítica visual, a imagem vem primeiro; para "o que
mudou?", o texto basta.

## 5. Não reler

- Arquivo que você acabou de editar não precisa ser relido: a ferramenta de edição já falharia se a
  troca não coubesse.
- Resultado de subagente já resumido não se reabre na fonte.
- Um agente retomado relê tudo que já leu: tarefa nova vai para agente novo.
