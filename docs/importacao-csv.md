# Importação e revisão de lançamentos por CSV

O primeiro formato aceito é um modelo simples em UTF-8, separado por ponto e vírgula. Ele serve para receitas e despesas de contas da SophIA; não é um importador específico de um banco.

```csv
data;descricao;tipo;valor;conta;categoria
10/10/2026;Compra do mercado;despesa;123,45;Conta principal;Alimentação
11/10/2026;Salário;receita;3.000,00;Conta principal;Salário
```

Regras do arquivo:

- O cabeçalho deve usar exatamente as seis colunas, nesta ordem.
- Datas usam `DD/MM/AAAA`; valores usam reais positivos com duas casas e vírgula decimal, como `123,45` ou `1.234,56`.
- `tipo` aceita `despesa` ou `receita`. Nome da conta e categoria deve corresponder a um registro ativo do próprio usuário. A categoria precisa ser do mesmo tipo.
- São aceitos até 500 lançamentos e 1 MB por arquivo. A linha de cabeçalho é a linha 1.
- Transferências entre contas, compras de cartão e pagamentos de fatura ficam fora deste formato. Eles exigem fluxos próprios para preservar os saldos e evitar contabilizar uma despesa duas vezes.

## API

1. Envie `POST /api/imports/transactions/preview` com JSON `{"csv_content":"..."}`. A prévia não grava nada; ela valida as referências e datas, converte valores com `Decimal` e aponta possíveis correspondências.
2. Revise cada linha. Uma correspondência `exact` tem mesma conta, data, tipo, valor e descrição normalizada. `similar` tem conta, data, tipo e valor iguais, mas a descrição difere. Linhas repetidas dentro do próprio arquivo também são sinalizadas. Não há deduplicação silenciosa.
3. Envie `POST /api/imports/transactions/confirm` com o mesmo `csv_content`, `preview_token`, `confirmed: true` e uma decisão por linha sinalizada: `IMPORT` ou `SKIP`. Sem a escolha para cada correspondência, a operação é recusada. Linhas sem correspondência só são criadas após a confirmação geral.

O token é assinado para a sessão e o usuário autenticado, expira em 15 minutos e vincula o conteúdo do CSV e o estado das correspondências. Se o arquivo ou as correspondências mudarem, é necessário gerar outra prévia. O arquivo não é armazenado pelo backend; a confirmação o envia novamente. A operação cria todos os movimentos aceitos em uma transação do banco.

Os registros importados usam o modelo atual de lançamento confirmado e são marcados com a origem existente `MANUAL`. Distinguir de forma persistente uma importação, guardar o arquivo original ou reconciliar uma linha do extrato com uma transação existente exige uma decisão de domínio e migração futuras. Por enquanto, o reconhecimento de duplicidade é uma sugestão na prévia, e a escolha entre importar ou ignorar é explícita.
