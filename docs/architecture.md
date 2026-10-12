# Arquitetura

## Serviços implementados

O monorepo separa a aplicação em processos independentes:

```text
Internet
   │ HTTPS (TLS na Cloudflare)
   ▼
Cloudflare Tunnel (conexão de saída; rede edge)
   │ HTTP interno, sem porta publicada no host
   ▼
Caddy (cabeçalhos de segurança; rede edge)
   │
Next.js (web; edge + app) ── proxy same-origin /api/* ──► FastAPI (api; app + data)
                                                               ├── sessão, TOTP e operações financeiras
                                                               ├── Finance Engine e ferramentas da IA
                                                               ├── OAuth ChatGPT ──► Responses API
                                                               └── PostgreSQL 17 (rede data interna)

Worker Python (processo independente; rede data; estende ocorrências previstas)
```

- `cloudflared` mantém conexões somente de saída com a Cloudflare e não publica portas. O hostname público é encaminhado para `caddy:80` dentro da rede `edge`.
- `caddy` não publica portas no host. Recebe HTTP somente pela rede Docker, aplica cabeçalhos de segurança e encaminha ao frontend; o TLS externo termina na Cloudflare.
- `web` atende a interface pela rede `edge` e encaminha chamadas `/api/*` para a API pela rede `app`. Em produção, a porta 3000 não é publicada no host e o contêiner não monta o código-fonte.
- `api` expõe autenticação, CRUD financeiro, filtros, resumos e health checks. Ao iniciar, aplica Alembic antes de iniciar o servidor.
- `Finance Engine` fica em `apps/api/app/finance_engine.py`; recebe movimentos tipados e calcula saldos e agregações com `Decimal`, sem depender de componentes web.
- `cards.py`, `transfers.py` e `invoices.py` expõem os comandos e consultas da Fase 2B; os cálculos de saldo, fatura, limite e ciclo continuam centralizados no Finance Engine.
- `postgres` fica apenas na rede Docker `data`, marcada como interna, sem mapeamento de portas.
- `worker` é um processo separado, conecta-se ao PostgreSQL pela rede de dados e estende diariamente o horizonte de ocorrências recorrentes; não há fila nem Redis.
- A interface autenticada abre no assistente. O mesmo menu mantém acesso às visões financeiras existentes; o painel de contexto lê dados já calculados pela API.
- `ai.py`, `ai_chat.py`, `ai_provider.py` e `ai_tools.py` isolam endpoints e persistência, o loop de streaming, o adaptador do provider e as operações financeiras permitidas. O provider padrão usa OAuth ChatGPT no backend (`store=false`); tokens ficam em volume privado montado somente na API. A chamada de ferramenta recebe o usuário da sessão autenticada e chama módulos financeiros existentes.
- Respostas chegam à web por Server-Sent Events. O backend persiste mensagens e auditoria, e transmite texto incremental e cartões estruturados sem expor chaves ao navegador.

O Compose usa dependências `service_healthy` para aguardar PostgreSQL e API. Em desenvolvimento, a web publica apenas `127.0.0.1:3000`; no perfil público, nenhuma porta é publicada no host. Requisitos e operação estão em [deployment.md](deployment.md).

## Núcleo financeiro manual — Fase 2A

O frontend chama os endpoints same-origin da API. A sessão determina `users.id`; cada consulta e gravação financeira filtra por esse proprietário. As referências de lançamentos também usam chaves estrangeiras compostas com `user_id`, protegendo o isolamento no banco.

As entidades implementadas são apenas `accounts`, `categories` e `transactions`. Contas guardam saldo inicial e data-base; saldos atuais são recalculados pelo Finance Engine a partir dos lançamentos confirmados. Categorias têm contexto de receita/despesa e arquivamento não destrutivo. Lançamentos são manuais e confirmados, com quantidade `NUMERIC(14,2)` e instante derivado da data civil `America/Sao_Paulo`.

O dashboard solicita saldos e resumos calculados pela API. O frontend recebe valores como strings decimais e apenas os formata em BRL; não soma, subtrai ou deriva totais financeiros.

## Transferências e cartões — Fase 2B

`transactions` continua sendo o registro financeiro único. `TRANSFER` contém origem e destino na mesma linha. `CARD_PURCHASE` contém categoria e fatura; `CARD_PAYMENT` contém a conta pagadora e a mesma fatura. A migration `0005_transfers_cards` cria `credit_cards` e `card_invoices` e amplia o schema de movimentos de forma incremental.

O total, os pagamentos, o saldo aberto e o status das faturas são derivados das transações relacionadas e do saldo inicial importado. `card_invoices.opening_balance` registra uma dívida que já existia antes do uso da SophIA; ela não cria uma compra nem uma despesa histórica. Uma dívida importada para um ciclo futuro também reduz o limite disponível imediatamente, pois representa compras/parcelas já assumidas; valores que ainda são apenas uma intenção de compra devem ficar fora da fatura. Assim, a compra conta como despesa uma vez e o pagamento não cria uma segunda. Saldos de conta consideram as duas pernas das transferências e o dinheiro usado nos pagamentos. O limite utilizado soma saldos abertos de faturas. O frontend apenas envia operações para a API e exibe valores já calculados.

O fechamento é inclusivo por data local: compra no dia configurado entra no ciclo que fecha naquele dia; depois dele, entra no ciclo seguinte. Em meses sem aquele dia, o fechamento é ajustado ao último dia do mês. O vencimento é o dia configurado posterior ao fechamento, no mesmo mês se possível; caso contrário, cai no mês seguinte. Faturas novas são materializadas quando surge a primeira compra do ciclo, evitando meses vazios sem atividade.

## Recorrências — Fase 2C.1

`recurrence_rules` guarda a programação e `recurrence_occurrences` materializa snapshots até 90 dias à frente. A migration `0008_recurring_occurrences` usa chaves compostas para o usuário, a regra, a conta e a categoria. Frequências mensais/anuais mantêm a âncora de início e ajustam dias inexistentes ao último dia do mês/ano.

O worker é um processo simples separado que executa a extensão diária do horizonte, sem fila ou infraestrutura adicional. `PLANNED`, `PENDING` e `OVERDUE` são apresentados a partir do estado armazenado e da data civil local. Uma ocorrência não participa do Finance Engine até que o usuário a registre: essa ação cria atomicamente uma única transação confirmada e marca a ocorrência como paga. Pular ou encerrar não cria movimento financeiro. O navegador chama endpoints autenticados e nunca calcula valores.

## Identidade e sessão

`users.id` é UUID e `auth_sessions.user_id` é uma chave estrangeira para `users.id`. O bootstrap controlado cria a conta inicial; não há cadastro público. Depois do bootstrap, somente a sessão autenticada do proprietário `gamercreeper74@gmail.com` pode usar `/api/admin/users` para listar, criar e excluir contas de login. Senhas iniciais têm ao menos 12 caracteres e são armazenadas com Argon2id via `argon2-cffi`. O login do proprietário exige senha e TOTP em produção; contas gerenciadas atualmente usam senha e ainda não têm MFA individual. Sessões são opacas: o navegador recebe um token aleatório e o banco armazena somente seu digest SHA-256. Em produção o cookie usa `__Host-`, `Secure`, `HttpOnly`, `SameSite=Strict`, caminho `/` e validade máxima de 24 horas. O pareamento inicial entrega um QR somente depois da senha e de um token temporário de administração; o QR expira em dez minutos e a confirmação associa o autenticador à conta proprietária. A chave Base32 continua no `.env` privado da VM. A API exige um cabeçalho de origem da própria aplicação em todas as gravações, além de `SameSite=Strict`.

A criação da primeira conta exige um token aleatório temporário e o TOTP do proprietário em produção. Um lock consultivo transacional do PostgreSQL protege o bootstrap entre processos; a rota retorna conflito depois da primeira conta. Não existe cadastro público contínuo. A migration de produção revoga as sessões antigas para exigir nova autenticação.

O endpoint de exclusão recusa remover o próprio proprietário e devolve `409` quando qualquer tabela de dados do usuário ainda contém registros. Somente sessões podem ser removidas em cascata; dados financeiros e pessoais são preservados. A interface solicita confirmação, e a API repete as verificações de autorização e integridade. A identidade é sempre obtida da sessão autenticada e os registros financeiros permanecem vinculados ao `users.id`; não aceite identificadores de usuário fornecidos por ferramentas de IA ou pelo cliente.

O limitador mantém memória limitada e aplica cotas por endereço de origem e por conta (identificador derivado com HMAC e segredo efêmero do processo) nos fluxos de autenticação e reautenticação. Reiniciar a API reinicia as cotas; Cloudflare também deve limitar tentativas nos endpoints de autenticação. O perfil público mantém uma única instância/worker da API. Ainda não há trilha persistente de auditoria financeira; alterações continuam visíveis no histórico de lançamentos, mas exclusões não formam um livro imutável.

A área “Minha conta” permite alterar o nome de exibição, consultar sessões ativas, encerrar outras sessões e trocar a senha. Revogar sessões e trocar senha exigem a senha atual e o TOTP, quando configurado. A troca de senha encerra todas as sessões, inclusive a atual. O TOTP é administrado no servidor; a interface não revela sua chave nem oferece redefinição self-service.

## Assistente conversacional

Mensagens financeiras simples e inequívocas podem ser interpretadas por parser determinístico. Um pedido completo de despesa fixa mensal cria uma prévia pela mesma ferramenta `create_recurrence` usada pelo modelo; a regra só é salva após confirmação. Se conta, categoria, valor, frequência ou período forem ambíguos, a mensagem vai ao modelo SMART para sugestão e esclarecimento. Categorias inferidas não são criadas sem autorização.

## Segurança de rede

Cloudflared, Caddy e frontend compartilham a rede `edge`; frontend e API também compartilham `app`. API participa de `app` e da rede `data` interna; PostgreSQL e worker só participam de `data`. A VM não publica portas do host, e o túnel não alcança diretamente API ou banco. Credenciais OAuth do provider ficam em volume privado disponível somente à API; não há chave de API no fluxo padrão. O token do túnel é montado como segredo do Compose e não deve ser salvo no repositório.

## Evolução planejada

O resumo mensal “A pagar” combina compromissos avulsos, ocorrências recorrentes e faturas abertas, mantendo valores previstos separados do saldo realizado. Avisos internos são atualizados ao abrir o app, voltar à aba e periodicamente enquanto o app está aberto; cada aviso aponta para o registro correspondente. Push e e-mail continuam futuros. Também seguem futuros o cálculo de amortização de financiamentos, investimentos reais e integração Pluggy. Agentes, embeddings e provedores de mensagem não fazem parte do assistente atual. Requisitos de produção, backup e restauração estão em [deployment.md](deployment.md); este documento público não registra endereços privados.


## Credenciais da IA no ambiente de desenvolvimento

O provider padrão da SophIA usa o OAuth do plano ChatGPT, sem API key. Tokens ficam em volume Docker montado somente na API, com permissão 0600; a VM renova tokens. O frontend e o worker não recebem essas credenciais. O Ollama é perfil opcional e nunca é fallback automático.
