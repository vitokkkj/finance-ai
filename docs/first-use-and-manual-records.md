# Primeiro uso e registros manuais

## Primeira configuração

Depois de criar a conta privada da SophIA, o primeiro uso pede o nome e o tipo de uma conta financeira. É necessário cadastrar uma conta para abrir o espaço financeiro; outras contas podem ser adicionadas depois.

O saldo inicial e a data em que aquele saldo vale são opcionais, mas precisam ser informados juntos. Use saldo zero quando ele for realmente zero. Deixe os dois campos vazios quando ainda não souber. É possível preencher ou corrigir essa base depois em **Contas**. O cadastro de cartão é opcional e pode ser feito logo após a conta ou mais tarde em **Cartões**.

O primeiro cadastro ativo de conta é a única opção e passa a ser o destino padrão quando o relato da conversa indicar claramente uma movimentação em conta. Se houver mais de uma conta ou cartão e nenhum padrão compatível, a SophIA pergunta qual deve usar. O padrão pode ser alterado em Preferências. A forma de pagamento precisa continuar clara: ter uma única conta não esclarece se uma compra foi feita no débito ou no crédito.

## Saldos conhecidos e desconhecidos

- A API representa como `null` o saldo inicial, a data-base e o saldo calculado quando a pessoa ainda não informou a base da conta.
- O banco exige que valor e data estejam ambos preenchidos ou ambos vazios.
- O Finance Engine não calcula o saldo individual de uma conta sem base.
- O saldo consolidado é `null` se não houver conta ativa ou se ao menos uma conta ativa não tiver saldo e data-base. A SophIA mostra quais contas precisam dessa informação e não apresenta a soma das contas conhecidas como se fosse o saldo total.
- Totais de receitas, despesas e resultado mensal continuam calculados a partir dos lançamentos confirmados; não dependem do saldo inicial.

## Primeiro lançamento pela interface

Receitas e despesas precisam de uma conta ativa e de uma categoria do tipo correspondente. Se faltar a conta, o formulário encaminha para criá-la e retorna ao lançamento. Se faltar a categoria, encaminha para criá-la, seleciona a nova categoria e volta ao formulário sem apagar os campos já preenchidos. A aplicação não cria categorias silenciosamente.

Quando há exatamente uma conta ou um cartão compatível, os formulários manuais preenchem essa opção. Com várias opções, o usuário escolhe; a SophIA segue a mesma regra na conversa. Um relato claro de algo já ocorrido pode ser registrado sem confirmação adicional. Correções de lançamentos existentes ainda exigem confirmação.

## Cobertura automatizada

Os testes de API cobrem a criação com saldo conhecido e desconhecido, a exigência do par saldo/data, o estado `null` no cálculo individual, a indisponibilidade do total consolidado se alguma conta ativa estiver incompleta, a preservação dos totais mensais e a recuperação do saldo ao preencher a base.
