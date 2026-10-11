# ADR 0004: Separar saldo corrente, reservas e obrigações previstas

## Status

Aceito.

## Contexto

Somar conta corrente, poupança, dinheiro e outros valores em um único “saldo total” pode fazer o usuário tratar reservas como caixa disponível. Ao mesmo tempo, um saldo realizado não informa quais pagamentos continuam vencendo no mês. Recorrências cobrem compromissos repetidos, mas não contas pontuais, e faturas em aberto precisam ser projetadas sem contar compras novamente como despesa.

## Decisão

- O valor principal chamado “saldo em contas correntes” soma somente contas ativas do tipo `CHECKING`. Poupança, dinheiro e outros tipos têm totais separados; saldo desconhecido em um tipo não invalida os outros.
- A projeção mensal combina recorrências planejadas, compromissos avulsos e saldo em aberto de faturas de cartão com vencimento até o fim do mês. Atrasos anteriores continuam visíveis e entram no total até serem pagos ou cancelados.
- O saldo realizado e o saldo projetado são exibidos separadamente. Compromisso previsto não altera o Finance Engine até virar transação confirmada.
- Um cartão pode apontar para a conta que normalmente paga sua fatura. Sem essa associação, a fatura continua no total a pagar, mas não reduz a projeção de qualquer tipo de conta.
- Anexos múltiplos no chat são evidência temporária. Até quatro imagens podem ser analisadas juntas; cada imagem passa por validação e normalização no backend. Bytes não entram no histórico, instruções dentro de imagem não são confiáveis e alterações financeiras exigem uma prévia confirmada.

## Consequências

- A interface deve qualificar sempre o saldo principal como saldo de contas correntes e separar visualmente outras reservas.
- Valores previstos e realizados usam o Finance Engine e operações `Decimal`; a IA só explica os dados estruturados.
- Associar uma conta pagadora é opcional para não presumir de onde sairá o dinheiro.
- O total projetado depende da completude da base de saldo do respectivo tipo e dos compromissos cadastrados; não é garantia de caixa.
- Marcar compromisso como pago deve ser idempotente e preservar o vínculo entre previsão e transação confirmada.
