# Instruções permanentes do projeto

## Produto e idioma

- A SophIA é um aplicativo financeiro pessoal e privado, administrado pelo proprietário `gamercreeper74@gmail.com`. Não há cadastro público; depois do bootstrap controlado, somente o proprietário pode criar contas de login pela área autenticada de administração. Cada pessoa vê somente os próprios registros financeiros, vinculados explicitamente ao `users.id` da sessão.
- Escreva textos da interface e documentação em português brasileiro (`pt-BR`). Preserve nomes oficiais de ferramentas e identificadores de código.
- Use BRL (`R$`) para valores exibidos e `America/Sao_Paulo` para datas e horários financeiros.
- Modele registros financeiros pertencentes a um usuário por relações explícitas com `users.id`. Obtenha o usuário da sessão autenticada; nunca espalhe identificadores fixos de usuário pelo código.

## Verdade financeira e dinheiro

- PostgreSQL e o Finance Engine são a fonte da verdade para dados e cálculos financeiros.
- A IA nunca calcula valores financeiros quando o sistema consegue calculá-los. Ela usa resultados estruturados do Finance Engine e pode explicá-los.
- Represente dinheiro com tipos decimais adequados no banco e operações decimais no backend. Nunca use `float` para valores monetários.
- Preserve semânticas distintas para despesas, receitas, transferências próprias, investimentos, reembolsos, compras e pagamentos de fatura. Não conte transferências próprias ou pagamentos de fatura como novas despesas.
- Registre cada transferência própria uma única vez, ligada às contas de origem e destino; ela altera os saldos individuais, mas não receitas, despesas ou saldo total entre contas.
- Trate cada compra no cartão como a despesa. O pagamento da fatura diminui a conta pagadora e o saldo devido, sem criar outra despesa.
- Derive totais, pagamentos, saldo aberto, uso de limite e status de fatura das transações associadas; não persista totais financeiros redundantes.
- Considere o dia de fechamento da fatura inclusivo e documente a regra de ciclo/vencimento em datas de fronteira e meses curtos.
- Regras financeiras precisam de testes que cubram valores, datas, timezone, recorrências e reconciliação conforme esses recursos forem implementados.

## Privacidade, segurança e integrações

- O aplicativo não oferece cadastro público. A criação inicial é controlada pelo bootstrap; a criação e exclusão de contas de login adicionais são restritas ao proprietário autenticado. Nunca apague dados financeiros em cascata ao remover um acesso.
- Nunca armazene senhas bancárias. Integrações bancárias são somente leitura.
- Segredos, credenciais, tokens e arquivos `.env` nunca entram no Git. Mantenha `.env.example` sem valores secretos.
- PostgreSQL não publica portas no host nem na internet; os serviços da aplicação o acessam por uma rede interna do Compose.
- Minimize dados pessoais enviados a provedores externos e nunca registre segredos em logs.
- Ferramentas de IA recebem a identidade da sessão autenticada; nunca aceite `user_id` fornecido pelo modelo nem dê acesso direto a SQL.
- A integração real com Pluggy e qualquer provedor de IA exigem documentação oficial atual antes de implementação.

## Arquitetura e mudanças

- Mantenha web, API, worker e banco como processos/serviços claramente separados.
- Implemente apenas o domínio necessário à fase em andamento. Registre conceitos futuros na documentação sem criar tabelas, interfaces ou camadas vazias antecipadamente.
- Mantenha regras de negócio fora do frontend. A API e o Finance Engine são responsáveis por validação e cálculos.
- Prefira módulos pequenos com responsabilidades claras e dependências explícitas. Adicione abstrações quando houver mais de uma implementação real ou uma necessidade concreta de teste/isolamento.
- Preserve idempotência em sincronizações e operações que possam ser repetidas.
- Nunca adicione serviços de infraestrutura como Redis ou filas sem necessidade demonstrada.

## Verificação

- Depois de mudanças, execute os testes, lint, type checking, migrations e builds disponíveis para os componentes alterados.
- Corrija falhas introduzidas antes de concluir. Se uma verificação depender de ferramenta ou serviço ausente, informe o bloqueio e os comandos pendentes com clareza.
