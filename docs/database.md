# Modelo de dados

## Implementado

### Assistente financeiro

- `ai_conversations`: UUID, proprietário `user_id`, título, arquivamento e timestamps. O usuário autenticado é o único escopo de leitura e escrita.
- `ai_messages`: UUID, proprietário e conversa com chave composta, papel (`USER`, `ASSISTANT`, `TOOL` ou `SYSTEM`), conteúdo, cartões estruturados opcionais, modelo, tokens, custo estimado e criação. A API da web expõe somente mensagens de usuário e assistente; resultados internos de ferramentas ficam no histórico privado.
- `ai_tool_calls`: proprietário, conversa e mensagem de origem com chaves compostas; ferramenta, argumentos e resumo de saída sanitizados, estado, duração, modelo, tokens e custo. Alterações sujeitas a confirmação permanecem `PENDING_CONFIRMATION` até confirmação ou cancelamento explícito.
- `ai_memories`: preferências de até 500 caracteres, salvas somente quando o usuário pedir explicitamente e associadas ao proprietário.

As chamadas de IA não recebem `user_id` como argumento. A API injeta o usuário da sessão na ferramenta e cada operação delega às consultas e comandos financeiros existentes. Credenciais OAuth e tokens do provider não são persistidos no banco nem retornados pela API; ficam em volume privado do serviço API.

### Identidade e sessões

- `users`: UUID, e-mail único normalizado, nome de exibição, hash Argon2id da senha, foto WebP otimizada opcional com revisão UUID e data de criação. A foto é servida somente pela API autenticada e não é incluída em respostas de lista ou logs.
- `auth_sessions`: digest SHA-256 do token de sessão, `user_id` com chave estrangeira e exclusão em cascata, validade e data de criação.

### Fase 2A — núcleo financeiro manual

- `accounts`: UUID, `user_id`, nome, tipo (`CHECKING`, `SAVINGS`, `CASH` ou `OTHER`), moeda fixa BRL, saldo inicial opcional `NUMERIC(14,2)`, data-base opcional, flag ativa e timestamps. Saldo e data-base são nulos em conjunto quando ainda não conhecidos; a restrição `ck_accounts_opening_balance_pair` impede um estado parcial.
- `categories`: UUID, `user_id`, nome, contexto (`INCOME` ou `EXPENSE`), `archived_at` e timestamps. Arquivar não apaga a linha nem suas referências históricas.
- `transactions`: UUID, `user_id`, `account_id`, `category_id`, tipo, origem (`MANUAL`), estado (`CONFIRMED`), descrição, valor positivo `NUMERIC(14,2)`, instante com timezone e notas opcionais.

Contas, categorias e lançamentos têm relação explícita com `users.id`. A tabela de lançamentos possui chaves estrangeiras compostas para `(account_id, user_id)` e `(category_id, user_id)`, além das verificações da API. Assim, uma referência não pode apontar para a conta ou categoria de outro usuário.

O schema usa restrições para limitar moeda a BRL, os tipos aceitos, origem/estado atuais e valores de lançamento positivos. Receita ou despesa define a direção do valor; o banco não armazena um valor negativo para representar despesa. As migrations `0002_accounts`, `0003_categories` e `0004_transactions` evoluem o banco sem antecipar tabelas de fases futuras.

### Fase 2B — transferências próprias e cartões

- `credit_cards`: UUID, `user_id`, nome, instituição opcional, limite `NUMERIC(14,2)`, BRL, dia de fechamento, dia de vencimento, estado ativo e timestamps. Restrições validam moeda, limite não negativo e dias entre 1 e 31.
- `card_invoices`: UUID, `user_id`, cartão, início/fim do ciclo, data de fechamento, vencimento, saldo inicial `opening_balance NUMERIC(14,2)` e criação. O saldo inicial começa em zero e pode representar dívida de uma fatura que já existia antes do uso da SophIA; ele não é uma despesa. O par cartão/usuário/data de fechamento é único. A chave composta `(credit_card_id, user_id)` exige que cartão e fatura tenham o mesmo proprietário.
- `transactions`: preserva os dados existentes da Fase 2A. `type` aceita `INCOME`, `EXPENSE`, `TRANSFER`, `CARD_PURCHASE` e `CARD_PAYMENT`. `account_id` e `category_id` tornam-se anuláveis somente para acomodar movimentos com referências próprias. Novos campos `source_account_id` e `destination_account_id` representam as duas pernas de uma transferência em uma linha; `card_invoice_id` conecta compras e pagamentos a uma única fatura.

Uma compra no cartão continua sendo uma única linha `CARD_PURCHASE` em `transactions`, com categoria e fatura. A fatura não duplica a compra: não guarda uma cópia ou o total acumulado. `total` deriva das compras com aquele `card_invoice_id`; `paid_amount` deriva dos pagamentos; `outstanding` é a diferença não negativa. Uma linha `CARD_PAYMENT` também guarda a conta que pagou, e pode haver várias por fatura.

O banco aplica chaves estrangeiras compostas para que contas, categorias e faturas referenciadas pertençam ao mesmo `user_id`. Restrições condicionais de tipo exigem as referências corretas para cada movimento e impedem uma transferência para a mesma conta. A migration incremental `0005_transfers_cards` não apaga nem reescreve transações anteriores. Seu downgrade é bloqueado quando já existem movimentos 2B, para não perder dados ao remover o schema que os representa.

O saldo inicial de fatura é adicionado de forma incremental por `0010_card_invoice_open_balance`, com valor padrão zero e restrição não negativa. A migration impede downgrade quando há saldo inicial positivo, para não descartar dívida importada.

A migration `0016_totp_replay` acrescenta em `users` o contador mais recente de TOTP consumido. O login, pareamento MFA e reautenticação atualizam o contador com uma condição atômica; códigos antigos ou já usados não podem ser repetidos.

## Convenções financeiras

- PostgreSQL usa `NUMERIC(14,2)`; Python usa `Decimal`; valores de resposta da API são strings decimais com duas casas.
- A interface envia valores monetários como texto decimal e não soma valores. O Finance Engine executa os cálculos.
- Quando informados, `opening_balance` e `opening_balance_date` representam o saldo no início do dia indicado. Os lançamentos confirmados dessa data em diante compõem o saldo. Quando ambos são nulos, o saldo daquela conta é desconhecido e a API o retorna como `null`.
- `checking_balance` soma somente contas correntes ativas e fica `null` se não houver corrente ativa ou se uma delas não tiver saldo/data-base. `account_type_balances` mantém saldos e contagens incompletas separados por tipo; uma poupança sem base não altera o saldo de contas correntes.
- Saldo de conta ativa = saldo inicial + receitas confirmadas + transferências recebidas − despesas confirmadas − transferências enviadas − pagamentos de fatura. Compras no cartão não alteram saldos bancários. Não há coluna mutável `current_balance`.
- Arquivar uma conta exige saldo conhecido igual a zero. Se o saldo for desconhecido ou diferente de zero, a API pede que o proprietário informe a base ou transfira/concilie o saldo antes, para o total ativo não ocultar dinheiro.
- Datas informadas pelo usuário são datas civis em `America/Sao_Paulo`. Para consultas, o início do dia/mês local vira o limite inferior inclusivo e o início do dia/mês seguinte vira o limite superior exclusivo, convertido para UTC.
- Uma categoria arquivada não pode ser usada em novo lançamento; lançamentos existentes continuam consultáveis pelo nome histórico da categoria.
- Todos os registros financeiros são sempre consultados e gravados no escopo do usuário autenticado.

## Fase 2C.1 e conceitos ainda futuros

### Fase 2C.1 — recorrências

- `recurrence_rules`: UUID, proprietário `user_id`, conta e categoria com chaves compostas de ownership, tipo de movimento, descrição, valor `NUMERIC(14,2)`, BRL, frequência, intervalo, início/fim, notas, estado ativo e timestamps. Restrições validam os tipos, valor positivo, frequência, intervalo e ordem das datas.
- `recurrence_occurrences`: UUID, proprietário, regra com chave composta, data prevista, snapshot de conta/categoria/tipo/descrição/valor/notas, estado (`PLANNED`, `PAID`, `SKIPPED`, `CANCELLED`) e vínculo opcional único com a transação criada ao registrar como paga. `rule_id + user_id + due_date` é único, tornando a materialização idempotente.
- Ocorrências guardam o snapshot para mudanças na regra não reescreverem o passado. Valores previstos não são transações e não entram no Finance Engine. Ao pagar, a transação confirmada existente vira a fonte dos efeitos financeiros; o vínculo permite retornar o mesmo resultado em chamadas repetidas.
- O vínculo único impede reutilizar a transação em outra ocorrência; o endpoint de exclusão de lançamentos recusa excluir transações vinculadas para preservar a idempotência.
- A migration incremental `0008_recurring_occurrences` cria essas tabelas e vínculos. Seu downgrade é bloqueado quando há regras ou ocorrências para não remover compromissos registrados.

### Fase 2C.2 — previsão e compromissos avulsos

- `planned_commitments`: UUID, proprietário, conta/categoria com chaves compostas, tipo, descrição, valor `NUMERIC(14,2)`, data prevista, observação, estado (`PLANNED`, `PAID`, `CANCELLED`) e vínculo opcional único com a transação criada ao pagar.
- `credit_cards.payment_account_id` associa opcionalmente a fatura a uma conta pagadora do mesmo proprietário. Fatura sem associação continua no total a pagar, sem reduzir projeção de conta.
- A API calcula `checking_balance`, saldos realizados/projetados por tipo e itens de previsão em tempo de consulta. Esses totais não são armazenados como colunas financeiras derivadas.
- A migration `0015_planned_commitments_and_card_payment_accounts` cria os compromissos e a associação pagadora.

### Conceitos futuros, ainda sem tabelas

Parcelamentos, financiamentos, investimentos, orçamentos, metas, notificações, integrações do Pluggy, embeddings e agentes continuam sem tabelas. A presença nesta lista não significa que façam parte do schema atual.
