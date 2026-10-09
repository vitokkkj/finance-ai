# Regras financeiras

## Invariantes permanentes

- PostgreSQL guarda os dados financeiros e o Finance Engine é a fonte dos saldos e resumos calculados.
- A IA explica resultados estruturados do Finance Engine; não soma transações nem calcula valores que o sistema pode calcular.
- Dinheiro usa `NUMERIC`/`DECIMAL` no banco e `Decimal` no backend. Valores são serializados como texto decimal. Não usar `float` para dinheiro.
- Datas financeiras seguem `America/Sao_Paulo`; valores e textos da aplicação usam BRL e `pt-BR`.
- Registros financeiros pertencem explicitamente ao `users.id` da sessão. Não existem IDs de usuário fixos no código.
- Integrações bancárias futuras serão somente leitura. Senhas bancárias nunca são armazenadas.

## Implementado na Fase 2A

- Tipos atuais de lançamento: `INCOME` e `EXPENSE`. O valor armazenado é sempre positivo; o tipo determina se ele soma ou subtrai.
- Saldo inicial da conta é um valor na abertura do dia de `opening_balance_date`.
- `opening_balance` e `opening_balance_date` são informados juntos ou ficam ambos nulos quando o saldo de abertura ainda é desconhecido. Nesse caso, o Finance Engine não calcula nem apresenta saldo para a conta. Se alguma conta ativa estiver sem essa base, o saldo consolidado também fica indisponível; os saldos das outras contas permanecem visíveis individualmente. Receitas, despesas e resultado mensal continuam calculáveis a partir dos movimentos registrados.
- Saldo da conta ativa = saldo inicial + lançamentos `CONFIRMED` do tipo `INCOME` − lançamentos `CONFIRMED` do tipo `EXPENSE`, desde a data-base até a data local atual.
- Não há saldo corrente mutável no banco. A API consulta os dados e pede ao Finance Engine que recalcule o saldo.
- Resumo mensal usa início local inclusivo e início do mês seguinte exclusivo. Dessa forma, o último dia do mês entra no período e transações do mês anterior ficam fora.
- A interface apresenta saldos, receitas, despesas, resultado e gastos por categoria recebidos da API. O navegador formata strings decimais sem realizar operações monetárias com `number`.
- Categorias separam receitas de despesas. Arquivar impede o uso em novos lançamentos e preserva o histórico existente.
- Conta ou categoria de outro usuário não pode ser referenciada num lançamento. A API verifica o proprietário e o PostgreSQL aplica chaves compostas no vínculo.

## Implementado na Fase 2B

- Uma transferência própria é uma única transação `TRANSFER` com origem, destino, valor e data. Ela reduz a conta de origem e aumenta a conta de destino pelo mesmo `Decimal`; não compõe receitas, despesas ou resultado mensal. Uma tarifa, quando registrada, é uma despesa separada.
- Uma compra `CARD_PURCHASE` conta como despesa na data da compra e na sua categoria. Ela fica vinculada a uma fatura e não muda saldos de contas bancárias.
- Uma fatura é identificada pelo cartão e pela data de fechamento. O período inclui o dia de fechamento. Compra até e inclusive o fechamento vai para esse ciclo; compra posterior vai para o próximo ciclo.
- Se o dia configurado não existir no mês, fechamento e vencimento usam o último dia válido. O vencimento fica no mesmo mês somente quando a data configurada é posterior ao fechamento; nos demais casos, fica no mês seguinte.
- `CARD_PAYMENT` representa cada pagamento como uma transação separada ligada à fatura e à conta pagadora. Reduz o saldo dessa conta e o saldo aberto da fatura; nunca entra de novo em despesas ou receitas. Uma fatura pode ter vários pagamentos parciais.
- Total da fatura é a soma das compras associadas. Valor pago é a soma de pagamentos confirmados. Saldo aberto é `max(total - pago, 0)`. Nenhum desses totais é persistido como fonte de verdade.
- Status é derivado: `OPEN` até o fim do dia de fechamento; `CLOSED` depois do fechamento se houver saldo e nenhum pagamento parcial; `PARTIALLY_PAID` enquanto houver saldo e pagamentos, antes do vencimento; `OVERDUE` depois do vencimento enquanto houver saldo; `PAID` quando o saldo chega a zero. Quitação pode ocorrer antes do fechamento; uma nova compra ainda dentro do ciclo recalcula o saldo e o status.
- Limite utilizado é o saldo aberto somado em todas as faturas do cartão. Limite disponível é o limite cadastrado menos esse uso; pagamentos parciais liberam limite na mesma proporção.
- Todas as datas de compra, pagamento, fechamento e vencimento são datas civis de `America/Sao_Paulo`.

## Fase 2C.1 — recorrências

- Uma regra recorrente descreve uma receita ou despesa prevista, com conta, categoria, valor positivo, frequência (`DAILY`, `WEEKLY`, `MONTHLY`, `YEARLY`), intervalo e datas civis de início e fim opcionais.
- Uma regra gera ocorrências previstas num horizonte móvel de 90 dias. O worker mantém esse horizonte; gerar a mesma faixa novamente é idempotente (`rule_id`, proprietário e data prevista são únicos).
- Frequências mensais e anuais permanecem ancoradas na data original. Se o dia não existir no mês/ano, usa-se o último dia válido sem deslocar os meses seguintes. Exemplo: dia 31 resulta em 28/29 de fevereiro e volta ao dia 31 no mês seguinte que o tiver.
- Uma ocorrência `PLANNED` tem estado de exibição `PENDING` quando vence hoje e `OVERDUE` depois do vencimento. Esses dois rótulos são derivados da data local de `America/Sao_Paulo` e não são estados persistidos.
- Ocorrências previstas não alteram saldos, receitas, despesas, resumos ou faturas. Ao registrar uma ocorrência como paga, o sistema cria uma única transação manual confirmada de receita/despesa na data atual local e vincula a ocorrência. Repetir a ação retorna a mesma transação.
- A transação vinculada não pode ser excluída pelo endpoint genérico de lançamentos; isso preserva o vínculo e impede que uma repetição crie outro movimento. A tentativa retorna conflito, sem apagar dados.
- Ignorar uma ocorrência marca somente aquela data como `SKIPPED` e não cria transação. Encerrar uma regra preserva seu histórico e cancela suas ocorrências futuras ainda previstas.
- Alterações podem se aplicar à ocorrência atual, à atual e futuras, ou ao modelo futuro da regra. Ocorrências pagas preservam o snapshot e o vínculo transacional originais.
- O primeiro vencimento não pode ser anterior à data local de criação. Datas de ocorrência precisam respeitar a data-base da conta. Conta e categoria permanecem vinculadas ao mesmo proprietário autenticado.

## Fora do escopo da Fase 2C.1

Parcelamentos, financiamentos, investimentos reais, reembolsos, previsões, orçamento, juros rotativos, notificações e sincronização bancária seguem fora desta fatia. Cada fluxo futuro terá semântica própria e testes de valor, data, timezone, idempotência e reconciliação.
