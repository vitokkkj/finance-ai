# Domínio financeiro da SophIA

Este contexto define a linguagem do registro financeiro pessoal. Ele distingue movimentos já ocorridos de compromissos que ainda são esperados.

## Movimentos e compromissos

**Transação**:
Um movimento financeiro que já aconteceu e foi confirmado no Finance Engine. Transações confirmadas compõem saldos e totais realizados.
_Evite_: previsão, ocorrência, parcela planejada.

**Relato de movimentação**:
Declaração do usuário de que um movimento financeiro já aconteceu. Não é uma previsão nem, por si só, uma autorização para a SophIA movimentar dinheiro.

**Confirmação de alteração**:
Autorização explícita para modificar uma transação existente. É diferente de confirmar que o movimento relatado aconteceu.

**Regra recorrente**:
Uma descrição reutilizável de uma receita ou despesa que deve se repetir segundo uma frequência e um intervalo.
_Evite_: transação recorrente, lançamento futuro.

**Ocorrência**:
Uma instância individual de uma regra recorrente, com data prevista e estado próprio. Uma ocorrência só afeta os valores realizados quando vinculada à transação criada ao registrá-la como paga.
_Evite_: série, transação.

**Ocorrência ignorada**:
Uma ocorrência que foi deliberadamente pulada e não deve criar transação.
_Evite_: despesa zero, pagamento cancelado.

**Sugestão de categoria**:
Uma opção inferida a partir da descrição do movimento. Não é uma categoria escolhida nem criada até o usuário confirmar ou pedir explicitamente.
_Evite_: classificação confirmada, aprendizagem automática.

**Prévia de compromisso**:
Resumo de uma regra futura antes de gravá-la. Exige confirmação e não altera saldo ou valores realizados.
_Evite_: pagamento, transação futura.

**Compromisso avulso**:
Receita ou despesa futura sem repetição, vinculada a uma conta, categoria e data prevista. Permanece fora dos valores realizados até ser marcada como recebida ou paga e ligada a uma transação.
_Evite_: transação futura, recorrência.

**Previsão de obrigações**:
Lista de ocorrências recorrentes não pagas, compromissos avulsos e faturas abertas com vencimento até o fim do mês. Inclui valores vencidos de meses anteriores e separa atrasados, próximos sete dias e restante do mês.
_Evite_: dívida confirmada, saldo atual.

**Saldo por tipo de conta**:
Saldo real ou projetado agrupado por conta corrente, poupança, dinheiro e outras contas. O valor principal chamado saldo em contas correntes contém somente contas do tipo `CHECKING`.
_Evite_: saldo total sem qualificar os tipos de conta.

**Saldo projetado**:
Estimativa separada do saldo real, obtida ao aplicar compromissos não pagos até o fim do mês e faturas abertas associadas a uma conta pagadora.
_Evite_: saldo atual, saldo garantido.

## Fontes de dados

**Registro manual**:
Movimento financeiro informado pelo usuário diretamente à SophIA, com base em um evento que já aconteceu.

**Dados bancários sincronizados**:
Informações de conta e movimentação obtidas de uma instituição financeira por integração somente leitura, após autorização do usuário.

**Movimento sincronizado**:
Movimentação confirmada pela instituição e importada para o Finance Engine como transação realizada.

**Movimentação bancária pendente**:
Movimentação que a instituição ainda não informa como efetivada; não compõe os totais realizados até ser confirmada.

**Organização local**:
Categoria, descrição ou observação ajustada pelo usuário em um registro sincronizado, sem alterar o valor, a data, a conta ou os dados mantidos pela instituição.

**Reconciliação de movimentação**:
Associação entre dados bancários e registros locais que identifica quando ambos representam o mesmo evento financeiro.

**Movimento em reconciliação**:
Movimento importado que pode corresponder a um registro manual e fica fora dos totais realizados até o usuário resolver a dúvida.

**Saldo calculado**:
Valor produzido pelo Finance Engine a partir do saldo inicial e das transações registradas.

**Saldo calculado incompleto**:
Resultado que não deve ser apresentado como saldo atual quando a data ou o valor de abertura ainda não foram informados. A incompletude afeta o resumo do tipo de conta correspondente; uma poupança incompleta não oculta o saldo de contas correntes. O acompanhamento de movimentos manuais ainda depende de o usuário registrar todos os movimentos desde a base informada.

**Saldo informado pela instituição**:
Valor de saldo reportado pelo banco em uma consulta ou sincronização, usado como referência de conferência.

**Extrato bancário**:
Conjunto de movimentações e informações de saldo de uma conta, informado pela instituição financeira para determinado período.

## Conversação financeira

**Aviso proativo**:
Informação financeira relevante oferecida pela SophIA sem uma pergunta imediata, habilitada explicitamente pelo usuário.

**Explicação financeira geral**:
Explicação de um conceito de finanças pessoais que não é calculada a partir dos registros financeiros do usuário.

**Sugestão financeira pessoal**:
Opção de orçamento ou organização baseada nos dados do usuário, sem substituir a decisão dele nem alterar registros financeiros.
