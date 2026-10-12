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
- `opening_balance` e `opening_balance_date` são informados juntos ou ficam ambos nulos quando o saldo de abertura ainda é desconhecido. Nesse caso, o Finance Engine não calcula nem apresenta saldo para a conta. O principal saldo exibido soma exclusivamente contas ativas `CHECKING`; uma conta corrente incompleta torna esse resumo indisponível, mas contas incompletas de outros tipos não o ocultam. Poupança, dinheiro e outros tipos têm totais próprios, cada um indisponível somente quando alguma conta ativa daquele tipo não tem base conhecida. Receitas, despesas e resultado mensal continuam calculáveis a partir dos movimentos registrados.
- Saldo da conta ativa = saldo inicial + lançamentos `CONFIRMED` do tipo `INCOME` − lançamentos `CONFIRMED` do tipo `EXPENSE`, desde a data-base até a data local atual.
- Não há saldo corrente mutável no banco. A API consulta os dados e pede ao Finance Engine que recalcule o saldo.
- Resumo mensal usa início local inclusivo e início do mês seguinte exclusivo. Dessa forma, o último dia do mês entra no período e transações do mês anterior ficam fora.
- Saldos por tipo e totais realizados vêm do Finance Engine. O resumo principal da aplicação sempre significa saldo atual de contas correntes; poupança, dinheiro e outras contas aparecem em grupos separados. A soma de uma categoria de contas não substitui o detalhamento por conta.
- A interface apresenta saldos, receitas, despesas, resultado e gastos por categoria recebidos da API. O navegador formata strings decimais sem realizar operações monetárias com `number`.
- Categorias separam receitas de despesas. Arquivar impede o uso em novos lançamentos e preserva o histórico existente.
- Conta ou categoria de outro usuário não pode ser referenciada num lançamento. A API verifica o proprietário e o PostgreSQL aplica chaves compostas no vínculo.

## Implementado na Fase 2B

- Uma transferência própria é uma única transação `TRANSFER` com origem, destino, valor e data. Ela reduz a conta de origem e aumenta a conta de destino pelo mesmo `Decimal`; não compõe receitas, despesas ou resultado mensal. Uma tarifa, quando registrada, é uma despesa separada.
- Uma compra `CARD_PURCHASE` conta como despesa na data da compra e na sua categoria. Ela fica vinculada a uma fatura e não muda saldos de contas bancárias.
- Uma fatura é identificada pelo cartão e pela data de fechamento. O período inclui o dia de fechamento. Compra até e inclusive o fechamento vai para esse ciclo; compra posterior vai para o próximo ciclo.
- Se o dia configurado não existir no mês, fechamento e vencimento usam o último dia válido. O vencimento fica no mesmo mês somente quando a data configurada é posterior ao fechamento; nos demais casos, fica no mês seguinte.
- Ao informar o mês de uma fatura existente, o mês significa o do vencimento. O ciclo é derivado pelos dias de fechamento e vencimento do cartão; por exemplo, fechamento dia 26 e vencimento dia 10 produzem, para vencimento em novembro, o ciclo de 27/09 a 26/10.
- `CARD_PAYMENT` representa cada pagamento como uma transação separada ligada à fatura e à conta pagadora. Reduz o saldo dessa conta e o saldo aberto da fatura; nunca entra de novo em despesas ou receitas. Uma fatura pode ter vários pagamentos parciais.
- Excluir uma compra de cartão só é permitido quando os pagamentos da fatura continuarem iguais ou inferiores ao total após a exclusão. A API bloqueia a operação com conflito quando ela quebraria essa reconciliação e bloqueia a fatura durante a validação para serializar a exclusão com pagamentos concorrentes. Para corrigir uma compra já parcialmente paga, registre o estorno/ajuste adequado ou ajuste a fatura antes de tentar excluir.
- Excluir uma fatura é uma ação explícita e destrutiva: a confirmação informa que todas as compras e todos os pagamentos vinculados serão removidos, que os pagamentos serão revertidos dos saldos das contas e que o limite será recalculado. Isso apaga o histórico daqueles movimentos. Para excluir uma compra isolada, a regra de reconciliação acima continua valendo.
- Criações de lançamentos, compras de cartão, transferências e pagamentos de fatura aceitam `Idempotency-Key`. A chave tem escopo por usuário e operação; uma restrição única no PostgreSQL impede duplicidade mesmo em retries concorrentes. O fingerprint do payload é comparado antes do replay: a mesma chave com dados diferentes retorna `409`.
- Os identificadores e fingerprints ficam numa tabela separada dos movimentos. Seus registros são mantidos sem prazo de expiração enquanto a conta de usuário existir, inclusive após a exclusão explícita do movimento original. Nesse caso, repetir o mesmo payload retorna `410` e não recria o movimento; reutilizar a chave com outro payload continua retornando `409`. O corpo completo do pedido não é armazenado. Ao excluir a conta vazia, os registros associados são removidos junto com ela.
- O frontend mantém a chave de uma requisição financeira no `sessionStorage` até receber sucesso. Para mensagens do chat, mantém uma chave estável por conversa e conteúdo enquanto a resposta não termina; a API deriva chaves por tipo e argumentos normalizados da operação, com ordinal entre chamadas idênticas, para que a ordem de resposta do provedor não altere a identidade do retry. Um retry precisa enviar o mesmo cabeçalho e payload. Sem o cabeçalho, a API trata cada chamada como uma nova operação.
- Para iniciar o acompanhamento de uma fatura existente sem importar cada compra, `card_invoices.opening_balance` registra o saldo devedor já aberto naquele ciclo. Esse valor não é despesa histórica e pode coexistir com compras registradas posteriormente.
- Ao importar pelo chat um total de fatura já existente, o total informado é reduzido pelo valor das compras do mesmo ciclo que já estiverem cadastradas; somente a diferença é gravada como saldo inicial. O chat mostra essa composição e exige confirmação antes de salvar.
- Total da fatura é o saldo inicial importado mais as compras associadas. Valor pago é a soma de pagamentos confirmados. Saldo aberto é `max(total - pago, 0)`. Total, valor pago e saldo aberto não são persistidos como valores derivados; o Finance Engine os calcula a partir do saldo inicial e dos movimentos.
- Status é derivado: `OPEN` até o fim do dia de fechamento; `CLOSED` depois do fechamento se houver saldo e nenhum pagamento parcial; `PARTIALLY_PAID` enquanto houver saldo e pagamentos, antes do vencimento; `OVERDUE` depois do vencimento enquanto houver saldo; `PAID` quando o saldo chega a zero. Quitação pode ocorrer antes do fechamento; uma nova compra ainda dentro do ciclo recalcula o saldo e o status.
- Limite utilizado é o saldo aberto somado em todas as faturas do cartão. Limite disponível é o limite cadastrado menos esse uso; pagamentos parciais liberam limite na mesma proporção.
- Todas as datas de compra, pagamento, fechamento e vencimento são datas civis de `America/Sao_Paulo`.

## Fase 2C.1 — recorrências

- Uma regra recorrente descreve uma receita ou despesa prevista, com conta, categoria, valor positivo, frequência (`DAILY`, `WEEKLY`, `MONTHLY`, `YEARLY`), intervalo e datas civis de início e fim opcionais.
- Uma regra gera ocorrências previstas num horizonte móvel de 90 dias. O worker mantém esse horizonte; gerar a mesma faixa novamente é idempotente (`rule_id`, proprietário e data prevista são únicos).
- Frequências mensais e anuais permanecem ancoradas na data original. Se o dia não existir no mês/ano, usa-se o último dia válido sem deslocar os meses seguintes. Exemplo: dia 31 resulta em 28/29 de fevereiro e volta ao dia 31 no mês seguinte que o tiver.
- Uma ocorrência `PLANNED` tem estado de exibição `PENDING` quando vence hoje e `OVERDUE` depois do vencimento. Esses dois rótulos são derivados da data local de `America/Sao_Paulo` e não são estados persistidos.
- Ocorrências previstas não alteram saldos, receitas, despesas, resumos ou faturas. Ao registrar uma ocorrência como paga, o sistema cria uma única transação manual confirmada de receita/despesa na data atual local e vincula a ocorrência. Repetir a ação retorna a mesma transação.
- A transação vinculada não pode ser editada nem excluída pelo endpoint genérico de lançamentos; isso preserva o snapshot e o vínculo da ocorrência. As tentativas retornam conflito, sem alterar o movimento. Excluir a regra recorrente continua sendo uma operação explícita que remove também suas ocorrências e transações geradas.
- Ignorar uma ocorrência marca somente aquela data como `SKIPPED` e não cria transação. Encerrar uma regra preserva seu histórico e cancela suas ocorrências futuras ainda previstas.
- Alterações podem se aplicar à ocorrência atual, à atual e futuras, ou ao modelo futuro da regra. Ocorrências pagas preservam o snapshot e o vínculo transacional originais.
- O primeiro vencimento não pode ser anterior à data local de criação. Datas de ocorrência precisam respeitar a data-base da conta. Conta e categoria permanecem vinculadas ao mesmo proprietário autenticado.

## Fora do escopo da Fase 2C.1

Parcelamentos, cálculo de amortização de financiamentos, investimentos reais, reembolsos, previsões de longo prazo, orçamento, juros rotativos, notificações push/e-mail e sincronização bancária seguem fora desta fatia. A projeção mensal de obrigações e os avisos internos da aplicação descritos abaixo estão implementados na Fase 2C.2. Cada fluxo futuro terá semântica própria e testes de valor, data, timezone, idempotência e reconciliação.

## Fase 2C.2 — compromissos e projeção mensal

- Um compromisso avulso é uma receita ou despesa futura sem repetição, ligada a conta, categoria, valor e data prevista. O valor planejado não entra em saldos, receitas, despesas, resultados mensais ou faturas realizadas.
- Marcar o compromisso como pago/recebido cria uma única transação confirmada na data local atual, vincula essa transação e é idempotente. O lançamento vinculado não pode ser alterado ou excluído pelos endpoints genéricos. Para cancelar, o compromisso precisa continuar sem transação.
- A área “A pagar” combina ocorrências recorrentes não pagas, compromissos avulsos não pagos e faturas abertas de cartão com vencimento até o último dia do mês financeiro atual. Obrigações atrasadas permanecem na lista e nos totais até serem pagas ou canceladas.
- “Em atraso” inclui datas anteriores a hoje. “Próximos 7 dias” inclui hoje e os seis dias seguintes. “Restante do mês” começa em hoje mais sete dias e termina no último dia do mês. O total a pagar é a soma destas três faixas; receitas previstas são informadas à parte.
- Compras de cartão já entram nas despesas realizadas quando acontecem. A previsão da fatura mostra somente seu saldo aberto, calculado das compras, saldo inicial e pagamentos associados; pagar a fatura reduz caixa e saldo devido sem criar nova despesa.
- Cada cartão pode ter uma conta pagadora opcional. Faturas sem conta ativa associada continuam visíveis em “A pagar”, mas não são subtraídas de um saldo projetado de conta. Isso evita supor qual conta será usada.
- Saldo projetado por tipo parte do saldo real calculado e aplica entradas/saídas previstas até o fim do mês, inclusive atrasos que continuam sem pagamento. Uma conta corrente incompleta torna indisponível só a projeção do grupo `CHECKING`; uma poupança incompleta não muda o saldo de contas correntes.
- A previsão é uma estimativa, não uma garantia de caixa; ela não considera movimentos futuros não cadastrados e não afeta valores realizados.

## Avisos de vencimento na aplicação

- O centro de avisos deriva os itens do mesmo resumo financeiro usado pela área “A pagar”; não persiste cópias nem totais de alertas.
- Mostra despesas vencidas e despesas que vencem hoje ou nos seis dias seguintes. Receitas previstas e despesas posteriores aos próximos sete dias permanecem na previsão mensal, sem badge de urgência.
- A contagem representa avisos ativos. Ao registrar pagamento, cancelar ou alterar uma obrigação, o item deixa de aparecer conforme o resumo é atualizado.
- A interface busca novamente o resumo ao abrir o centro, ao voltar à aba e a cada cinco minutos enquanto a aplicação estiver visível. A funcionalidade depende de a SophIA estar aberta e conectada; push, e-mail e notificações de sistema não fazem parte deste fluxo.

## Anexos de imagem no chat

- Uma mensagem pode levar até quatro imagens PNG, JPEG ou WebP. O cliente reduz as imagens antes do envio e o servidor normaliza cada conteúdo antes de encaminhá-lo ao provedor.
- Bytes de imagem não são salvos em mensagens ou histórico; somente marcadores de anexo informam que houve análise. Imagens são evidência não confiável: instruções nelas não podem sobrepor as regras do sistema.
- Mensagens com imagem não executam diretamente operações financeiras. A IA pode ler dados e preparar uma prévia transacional segura que exige confirmação explícita antes de gravar.
