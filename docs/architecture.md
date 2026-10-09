# Arquitetura

## Serviços implementados

O monorepo separa quatro processos:

```text
Navegador
   │ localhost:3000
   ▼
Next.js (web) ── proxy same-origin /api/* ──► FastAPI (api) ── OAuth ChatGPT ──► Responses API
                                                   ├── autenticação e operações financeiras
                                                   ├── Finance Engine e ferramentas explícitas da IA
                                                   └── PostgreSQL 17

Worker Python (processo independente, sem jobs nesta fase)
```

- `web` atende a interface e encaminha chamadas `/api/*` para a API. Apenas a porta do frontend é publicada no host.
- `api` expõe autenticação, CRUD financeiro, filtros, resumos e health checks. Ao iniciar, aplica Alembic antes de iniciar o servidor.
- `Finance Engine` fica em `apps/api/app/finance_engine.py`; recebe movimentos tipados e calcula saldos e agregações com `Decimal`, sem depender de componentes web.
- `cards.py`, `transfers.py` e `invoices.py` expõem os comandos e consultas da Fase 2B; os cálculos de saldo, fatura, limite e ciclo continuam centralizados no Finance Engine.
- `postgres` fica apenas na rede Docker `data`, marcada como interna, sem mapeamento de portas.
- `worker` é um processo separado, conecta-se ao PostgreSQL pela rede de dados e estende diariamente o horizonte de ocorrências recorrentes; não há fila nem Redis.
- A interface autenticada abre no assistente. O mesmo menu mantém acesso às visões financeiras existentes; o painel de contexto lê dados já calculados pela API.
- `ai.py`, `ai_chat.py`, `ai_provider.py` e `ai_tools.py` isolam endpoints e persistência, o loop de streaming, o adaptador do provider e as operações financeiras permitidas. O provider padrão usa OAuth ChatGPT no backend (`store=false`); tokens ficam em volume privado montado somente na API. A chamada de ferramenta recebe o usuário da sessão autenticada e chama módulos financeiros existentes.
- Respostas chegam à web por Server-Sent Events. O backend persiste mensagens e auditoria, e transmite texto incremental e cartões estruturados sem expor chaves ao navegador.

O Compose usa dependências `service_healthy` para aguardar o PostgreSQL antes das migrations, e a API antes do frontend e do worker. O ambiente atual de testes roda numa VM Debian com web vinculado ao IP Tailscale e acesso direto pelo tailnet; API e PostgreSQL não publicam portas. A publicação futura em `sophia.matheus.inf.br` está em [deployment.md](deployment.md).

## Núcleo financeiro manual — Fase 2A

O frontend chama os endpoints same-origin da API. A sessão determina `users.id`; cada consulta e gravação financeira filtra por esse proprietário. As referências de lançamentos também usam chaves estrangeiras compostas com `user_id`, protegendo o isolamento no banco.

As entidades implementadas são apenas `accounts`, `categories` e `transactions`. Contas guardam saldo inicial e data-base; saldos atuais são recalculados pelo Finance Engine a partir dos lançamentos confirmados. Categorias têm contexto de receita/despesa e arquivamento não destrutivo. Lançamentos são manuais e confirmados, com quantidade `NUMERIC(14,2)` e instante derivado da data civil `America/Sao_Paulo`.

O dashboard solicita saldos e resumos calculados pela API. O frontend recebe valores como strings decimais e apenas os formata em BRL; não soma, subtrai ou deriva totais financeiros.

## Transferências e cartões — Fase 2B

`transactions` continua sendo o registro financeiro único. `TRANSFER` contém origem e destino na mesma linha. `CARD_PURCHASE` contém categoria e fatura; `CARD_PAYMENT` contém a conta pagadora e a mesma fatura. A migration `0005_transfers_cards` cria `credit_cards` e `card_invoices` e amplia o schema de movimentos de forma incremental.

O total, os pagamentos, o saldo aberto e o status das faturas são derivados das transações relacionadas. Assim, a compra conta como despesa uma vez e o pagamento não cria uma segunda. Saldos de conta consideram as duas pernas das transferências e o dinheiro usado nos pagamentos. O limite utilizado soma saldos abertos de faturas. O frontend apenas envia operações para a API e exibe valores já calculados.

O fechamento é inclusivo por data local: compra no dia configurado entra no ciclo que fecha naquele dia; depois dele, entra no ciclo seguinte. Em meses sem aquele dia, o fechamento é ajustado ao último dia do mês. O vencimento é o dia configurado posterior ao fechamento, no mesmo mês se possível; caso contrário, cai no mês seguinte. Faturas novas são materializadas quando surge a primeira compra do ciclo, evitando meses vazios sem atividade.

## Recorrências — Fase 2C.1

`recurrence_rules` guarda a programação e `recurrence_occurrences` materializa snapshots até 90 dias à frente. A migration `0008_recurring_occurrences` usa chaves compostas para o usuário, a regra, a conta e a categoria. Frequências mensais/anuais mantêm a âncora de início e ajustam dias inexistentes ao último dia do mês/ano.

O worker é um processo simples separado que executa a extensão diária do horizonte, sem fila ou infraestrutura adicional. `PLANNED`, `PENDING` e `OVERDUE` são apresentados a partir do estado armazenado e da data civil local. Uma ocorrência não participa do Finance Engine até que o usuário a registre: essa ação cria atomicamente uma única transação confirmada e marca a ocorrência como paga. Pular ou encerrar não cria movimento financeiro. O navegador chama endpoints autenticados e nunca calcula valores.

## Identidade e sessão

`users.id` é UUID e `auth_sessions.user_id` é uma chave estrangeira para `users.id`. Sessões são opacas: o navegador recebe um token aleatório em cookie `HttpOnly`, `SameSite=Strict`; o banco armazena somente seu digest SHA-256. Senhas são armazenadas com Argon2id via `argon2-cffi`. A API aplica limite local de tentativas de login. O cookie `Secure` fica ligado por padrão; o Compose de desenvolvimento o desliga para HTTP em `localhost`.

A interface permite a criação da primeira conta enquanto não existe usuário. Depois, essa rota retorna conflito. Não existe endpoint de cadastro público contínuo.

MFA/TOTP e trilha persistente de auditoria ainda não fazem parte desta fundação local; devem ser concluídos antes de expor a aplicação remotamente.

## Segurança de rede

O navegador acessa a aplicação pelo frontend. A API e o banco não têm portas publicadas. PostgreSQL e worker compartilham apenas a rede de dados interna; a API participa das redes de aplicação e de dados para atender o frontend e consultar o banco. A chave do provider é injetada somente no serviço da API.

## Evolução planejada

Parcelamentos, financiamentos, investimentos reais, previsões, notificações e Pluggy continuam futuros. Agentes, embeddings e provedores de mensagem não fazem parte do assistente atual. O ambiente de testes não é adequado a dados reais; o Cloudflare Tunnel e o modo de produção seguem pendentes.


## Credenciais da IA no ambiente de desenvolvimento

O provider padrão da SophIA usa o OAuth do plano ChatGPT, sem API key. Tokens ficam em volume Docker montado somente na API, com permissão 0600; a VM renova tokens. O frontend e o worker não recebem essas credenciais. O Ollama é perfil opcional e nunca é fallback automático.
