# ADR 0001: Materializar ocorrências recorrentes

## Status

Aceito para a Fase 2C.1.

## Contexto

Regras recorrentes precisam produzir itens individuais que possam ser pagos, ignorados ou ajustados sem alterar outros itens da série. O sistema também precisa continuar calculando os valores realizados exclusivamente a partir de transações confirmadas.

## Decisão

Persistir cada ocorrência com uma cópia dos campos financeiros da regra e uma data prevista única por regra. Alterações de uma ocorrência podem ficar locais ou atualizar também a regra e o conjunto definido pelo escopo. Ocorrências pagas mantêm vínculo obrigatório com uma transação confirmada; ignorar uma ocorrência não cria transação.

O worker mantém um horizonte móvel de 90 dias. A criação da regra gera esse horizonte imediatamente; o worker o estende diariamente. A geração é idempotente por `(rule_id, due_date)` e não usa fila externa.

`PLANNED`, `PENDING` e `OVERDUE` são estados exibidos derivados da data local e do estado terminal persistido. `PAID`, `SKIPPED` e `CANCELLED` são estados persistidos.

## Consequências

- Saldos e resumos permanecem baseados apenas em transações confirmadas.
- Cada ocorrência pode ter estado, campos e transação próprios.
- O worker acessa PostgreSQL para manter o horizonte, sem Redis ou outro serviço de fila.
- Ocorrências anteriores continuam auditáveis mesmo quando a regra da série é alterada ou cancelada.
