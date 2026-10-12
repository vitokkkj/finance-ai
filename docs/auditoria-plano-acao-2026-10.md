# Auditoria geral da SophIA — plano de ação

**Data-base:** 12/10/2026
**Escopo:** revisão de UX/UI, domínio financeiro, segurança, testes, GitHub Actions, documentação, integrações e operação. Este documento preserva o estado inicial da auditoria e acompanha as ações; não afirma que uma correção foi aplicada sem evidência verificável.

## Como interpretar as evidências

- **Código local** descreve o checkout revisado. Não prova que esse código esteja publicado na VM.
- **Serviço público observado** descreve respostas HTTP obtidas em 12/10/2026. Health checks e cabeçalhos não provam integridade completa do host ou dos dados.
- **VM:** houve inspeção direta por SSH nesta rodada; estado dos serviços, commit e schema foram registrados abaixo. A zona Cloudflare foi inspecionada e uma regra de rate limit foi aplicada. Proxmox não foi acessado diretamente. A chave do host foi validada sem ignorar nem contornar a verificação; o caminho de rede anterior à VM segue sem confirmação.
- As linhas citadas são referências do checkout na data da auditoria e podem mudar com alterações posteriores.
- Testes E2E usam somente dados sintéticos. A suíte mockada não substitui o cenário integrado; o cenário integrado usa banco descartável, nunca dados de produção.

## Atualização final da execução — 12/10/2026

**Código e CI:** a versão implantada está em `main` no SHA `41368d93bd96c4e1814890d29110323fbec5e864`. A execução [38317703475](https://github.com/vitokkkj/finance-ai/actions/runs/38317703475) passou nos jobs API, Frontend e imagens/runtime: lint/tipos, migrations e suíte PostgreSQL, E2E Playwright, auditorias de dependências e builds. No SHA anterior `eae1caf`, a CI encontrou uma falha de recuperação após conflito concorrente: o handler acessava `user.id` antes do rollback da sessão SQLAlchemy. O código agora captura o UUID antes das gravações e o reutiliza nos quatro endpoints; a CI corrigida passou. Localmente, API: 196 testes passaram e 3 foram ignorados por serem verificações POSIX ou concorrência PostgreSQL exclusiva da CI; Ruff e mypy passaram.

**Contas de login:** o proprietário confirmou que contas adicionais são usuários de login do app e devem poder ser criadas somente por ele. A aplicação permite listar/criar/excluir contas gerenciadas apenas na área do proprietário, mantém cadastro público desabilitado e recusa `DELETE` do próprio proprietário ou de usuário com dados associados (`409`). A criação/exclusão E2E usa conta sintética. A conta mencionada pelo proprietário e os dados reais não foram consultados nem excluídos. Atualização local posterior: MFA individual obrigatório foi implementado no backend, com segredo Fernet por conta e fluxo administrativo de reset; migration `0019_managed_user_totp` ainda está somente no checkout e não há evidência de CI ou deploy dessa mudança.

**Deploy e banco:** com autorização do proprietário, o commit `41368d93bd96c4e1814890d29110323fbec5e864` foi publicado na VM depois de CI verde. A migration `0018_idempotency_tombstones` foi aplicada e confirmada como head. Os seis serviços Compose estão ativos; API, web e PostgreSQL estão saudáveis. Health live/ready retornaram `200`, e `/api/accounts` e `/api/admin/users`, sem sessão, retornaram `401`; `/api/docs` retornou `404`. Os cabeçalhos HSTS, CSP, MIME sniffing, framing, Referrer-Policy e Permissions-Policy foram conferidos. Inspeção Docker confirmou que API, web, PostgreSQL e Caddy não publicam portas no host. SSH continua ativo com as opções escolhidas pelo proprietário.

**Backup pré-deploy:** antes da migration, foi criado um dump PostgreSQL temporário em formato custom, 143.674 bytes, modo `0600`, sem criptografia. `pg_restore --list` passou dentro do container PostgreSQL sem abrir registros; após deploy e health checks, o arquivo foi removido e sua ausência confirmada. O host não tinha `pg_restore`; a validação foi concluída com a ferramenta do container. O proprietário confirmou backup criptografado e restore testado no Proxmox; não houve inspeção direta dos jobs, retenção ou restore drill nessa execução. Não foram lidos `.env`, tokens, e-mails, transações nem saldos.

**Cloudflare:** a regra **Autenticacao - limite por IP** foi ativada na zona, somente para `finance.ruralflow.com.br`, `POST` e as rotas de setup, verificação/login e pareamento MFA. O teto é 20 requisições por IP em 10 segundos; o bloqueio dura 10 segundos. O painel validou a expressão e mostrou status ativo, com zero eventos no instante da conferência. Não foi provocado bloqueio de teste em produção. O limite da API por conta e IP continua ativo como proteção adicional.

**SSH:** TCP/22 permanece acessível conforme escolha do proprietário. `sophia` mantém senha e chave e pode usar `su -`; root aceita somente chave pública. `sshd -T` confirmou `PasswordAuthentication yes`, `PermitRootLogin without-password` (equivalente a `prohibit-password`) e `AllowUsers sophia root`. O daemon SSH está ativo; a chave Ed25519 dedicada foi testada com login root e permanece fora do repositório. A rede anterior à VM não foi inspecionada.

| P1 | Situação final |
|---|---|
| 1.1 — CI | Corrigida; três jobs verdes no SHA aplicado `41368d9` (run `38317703475`). O run intermediário `38317180381` revelou e permitiu corrigir a recuperação da sessão após conflito concorrente. |
| 1.2 — reconciliação financeira | Regras para compra paga e ocorrência paga protegidas, com regressões cobertas; código implantado. |
| 1.3 — idempotência | Lançamentos, transferências, compras e pagamentos persistem chave e tombstone por usuário/operação; enquanto o movimento existe, retries repetem o resultado. Após exclusão, a mesma operação retorna `410` sem recriá-lo; payload distinto retorna `409`. Migration `0018` aplicada na VM. |
| 1.4 — PostgreSQL na CI | PostgreSQL 17, `alembic upgrade head`, `alembic check`, suíte de API e auditoria de dependências passaram no CI `38317703475`. |
| 1.5 — E2E | Os testes E2E Playwright, auditoria JavaScript, lint/tipos e build passaram no job Frontend do CI `38317703475`. |
| 1.6 — gate e documentação de deploy | CI verde exigida no SHA exato; deploy manual documentado e executado no SHA verificado. Ruleset `24959980` exige PR e os três checks na `main`, sem aprovação humana. |
| 1.7 — contas e rate limit | Administração segura de usuários implantada; regra de borda Cloudflare criada e ativa. MFA individual foi promovido a P1.9 e tem implementação local pendente de CI/deploy. |
| 1.8 — VM | Inspeção, atualização e migration concluídas. Todos os serviços ativos e endpoints públicos verificados; caminho de rede anterior à VM e evidência direta do Proxmox continuam sem validação independente. |
| 1.9 — MFA individual gerenciado | Backend e testes implementados no checkout local: segredo TOTP próprio por conta, cifrado com Fernet; pareamento exige senha, rate limit e expira em dez minutos; login exige TOTP e consome contador anti-replay; reset exige sessão, senha e TOTP do proprietário, revoga sessões da conta e preserva dados financeiros. A suíte API local completa passou: 203 testes, 3 ignorados por verificações POSIX ou concorrência reservada à CI, 2 avisos existentes; os 30 testes direcionados também passaram. Ruff e mypy nos módulos alterados passaram. Migration `0019_managed_user_totp` está local, não aplicada na VM; `0020_transaction_cursor_index` também está local e depende de 0019. Ainda não há execução CI nem deploy para este conjunto. A chave Fernet de produção não foi provisionada nesta tarefa. |

**VM:** Debian 13; o checkout está no SHA `41368d9`; Alembic `0018_idempotency_tombstones (head)`; seis serviços ativos. Após o deploy havia 8,7 GB livres de 40 GB (77% usados) e 7,3 GiB de memória disponível. A contagem de usuários da inspeção inicial é histórica e não foi repetida; nenhum registro de Richard foi lido.

**Falhas e limitações remanescentes:** um CI intermediário (run `38317180381`) falhou no teste concorrente; a sessão inválida estava sendo consultada antes do rollback e foi corrigida no SHA implantado. No deploy atual, o host não tinha `pg_restore`; a listagem do dump passou pelo binário no container PostgreSQL. `docker compose port` retorna código de erro quando um serviço não publica a porta; `docker inspect` confirmou os bindings nulos, sem portas expostas. A checagem HEAD de readiness retornou `405` porque o endpoint aceita GET; a repetição com GET retornou `200` e todos os cabeçalhos esperados. O reload inicial do SSH em execução anterior falhou por ativação por socket; o serviço foi iniciado, `sshd -t` passou e o login por chave root funcionou. O serviço Docker não é acessível pela conta `sophia` sem privilégio, por desenho. O Docker Desktop local estava indisponível; a CI executou builds/imagens e migrations em Linux/PostgreSQL. O lint tem quatro avisos existentes de `!important` na regra `prefers-reduced-motion`. A CI não encontrou vulnerabilidades em `npm audit` nem `pip-audit`. As actions estão fixadas em releases compatíveis com Node 24. O ruleset `24959980` exige PR e os três checks na `main`, sem aprovação humana, bypass, exclusão ou force-push; a execução do PR atual deve confirmar os contextos.

## Estado inicial registrado

| Área | Estado observado antes das ações deste plano |
|---|---|
| Git | `main` local alinhado a `origin/main` no SHA `542f69e`; havia arquivos não rastreados `.agents/`, `docs/skills.md` e `sophia_logo_refinada.png`, preservados. |
| CI GitHub | Execução pública #47 do SHA `542f69e` falhou no job API, etapa combinada de lint/tipos/testes; frontend e runtime passaram. Execuções #46 e #44 também falharam na API. A anotação pública não identificou o comando causador; logs detalhados exigem autenticação. `pip-audit` foi ignorado após a falha. |
| E2E | A suíte Playwright local passou em 22 cenários. Os fluxos interceptam as chamadas à API e simulam sessão autenticada; o workflow não executava `test:e2e`. |
| Serviço público | `GET /api/health/live` e `/api/health/ready` retornaram 200; readiness indicou banco `ok`. Sem sessão, `/api/accounts` retornou 401 e `/api/docs` retornou 404. Foram observados HSTS, CSP, `X-Frame-Options`, `X-Content-Type-Options`, Referrer-Policy e Permissions-Policy. |
| VM | Não houve inspeção direta por SSH. A resposta HTTP pública não comprova estado de recursos, containers, versão instalada, migrations atuais ou recuperação. |
| Segurança perimetral | A revisão anterior no repositório registrou Cloudflare Free sem regras customizadas nem rate limiting configurado. Isso é evidência documental anterior, não confirmação do painel na data atual. A política do host também precisa de validação direta. |
| Dados/backup | `docs/deployment.md` registra confirmação operacional do proprietário em 12/10/2026 de backup criptografado e restauração testada; o README de infraestrutura ainda pede validar cópia/restauração. O estado real no Proxmox não foi verificado nesta auditoria. |
| Integração bancária | Pluggy/MeuPluggy é candidata futura. Não há integração bancária implementada; importação OFX também permanece decisão futura. |

Fontes principais: [workflow de qualidade](../.github/workflows/quality.yml), [scripts web](../apps/web/package.json), [guia de implantação](deployment.md), [revisão anterior](revisao-geral-ux-seguranca-2026-10.md), [integrações](integrations.md), [README de infraestrutura](../infra/README.md).

## Prioridade P1 — resultados, evidências e trabalho em andamento

Os itens P1 abaixo são acompanhados por evidência e estado de código/VM. Uma correção local ou CI verde não equivale a deploy; a versão publicada só é considerada atualizada após verificar SHA, migration, serviços e health checks.

### P1.1 Corrigir e tornar verde a validação do SHA implantável

**Evidência:** a execução #47 para `542f69e` falhou no job API. O workflow combina Ruff, checagem de tipos e pytest em uma etapa, então o resumo público não identifica qual deles falhou; `pip-audit` fica condicionado ao sucesso anterior. O mesmo job foi reportado como falho nas execuções #46 e #44.

**Ação:** obter logs autenticados, identificar e corrigir a causa, separar etapas para diagnóstico útil e exigir uma execução verde para o SHA candidato a deploy. Documentar o SHA validado e a relação entre aprovação de CI e deploy manual.

**Resultado:** as etapas de lint/tipos, migrations PostgreSQL, suíte de API, auditoria de dependências, E2E e imagens/runtime estão separadas para diagnóstico. O SHA implantado `41368d93bd96c4e1814890d29110323fbec5e864` passou nos três jobs do [run 38317703475](https://github.com/vitokkkj/finance-ai/actions/runs/38317703475); a revisão documental também passou nos três jobs do run `38318642073`.

**Referências:** [quality.yml](../.github/workflows/quality.yml), [quality.yml — auditoria Python](../.github/workflows/quality.yml), [deployment.md — deploy manual](deployment.md).

### P1.2 Preservar reconciliação ao editar/excluir compras e ocorrências pagas

**Evidência:** exclusão de transações ligadas a faturas ou recorrências é tratada em `finance_deletion.py`; os totais de fatura limitam saldo em aberto a zero (`max(total - pago, 0)`). A edição genérica impede apenas vínculo a compromisso planejado; não bloqueia de forma equivalente transação gerada por ocorrência de recorrência já paga. Isso pode deixar pagamentos acima das compras da fatura ou valores realizados divergentes da ocorrência original.

**Ação:** impedir exclusão/redução de compras que já tenham pagamentos associados, ou oferecer operações explícitas e auditáveis de estorno/crédito/chargeback; impedir edição de transação de ocorrência paga ou atualizar atomicamente o vínculo e os valores da ocorrência. Definir política de cancelamento versus remoção de histórico e cobrir saldos, pagamentos parciais/totais, recorrência e reconciliação com testes.

**Atualização da implementação:** a compra individual continua bloqueada se sua exclusão fizer pagamentos excederem o total restante. Regressões cobrem compra parcialmente paga, totalmente paga e compra cuja exclusão é permitida porque outra mantém cobertura; também confirmam que a exclusão explícita da fatura reverte o saldo da conta e apaga compras/pagamentos conforme o aviso de confirmação. A suíte PostgreSQL passou no run `38317703475`; a correção está implantada no SHA `41368d93bd96c4e1814890d29110323fbec5e864`.

**Referências:** [finance_deletion.py](../apps/api/app/finance_deletion.py), [finance_engine.py](../apps/api/app/finance_engine.py), [transactions.py — edição](../apps/api/app/transactions.py), [recurrences.py — baixa](../apps/api/app/recurrences.py), [financial-rules.md](financial-rules.md).

### P1.3 Adicionar idempotência a operações financeiras repetíveis

**Evidência:** os endpoints de criação de transferência, lançamento e pagamento/criação de compra não apresentam chave de idempotência. Repetição após timeout ou retry pode criar mais de um registro; deduplicação por valor/data não é segura, pois movimentos iguais podem ser legítimos.

**Ação:** aceitar chave de idempotência ligada ao usuário autenticado, operação e payload; persistir resultado de forma transacional e definir prazo/retorno para replay. Cobrir timeout/retry concorrente e rejeitar reutilização da chave com payload diferente.

**Atualização da implementação:** a migration `0018_idempotency_tombstones` conserva fingerprints e IDs depois da exclusão de movimentos. Enquanto o movimento original existe, o mesmo payload retorna o resultado original. Depois de sua exclusão explícita, o mesmo payload retorna `410` sem recriar o movimento; payload diferente retorna `409`. Os metadados mínimos permanecem enquanto a conta existir, sem expiração; o chat/frontend reutiliza uma chave estável durante retries. Testes locais cobrem lançamento, transferência, compra de cartão, pagamento, exclusão e retry; a concorrência real e a migration PostgreSQL passaram no run `38317703475`. A migration está aplicada na VM e é o head `0018_idempotency_tombstones`.

**Referências:** [transfers.py](../apps/api/app/transfers.py), [transactions.py](../apps/api/app/transactions.py), [invoices.py — compra](../apps/api/app/invoices.py), [invoices.py — pagamento](../apps/api/app/invoices.py).

### P1.4 Exercitar PostgreSQL e Alembic na CI

**Evidência:** a configuração CI usa SQLite em memória. A fixture cria tabelas com `Base.metadata.create_all`; não percorre migrations PostgreSQL nem garante comportamento idêntico de chaves estrangeiras, locks ou concorrência.

**Ação:** adicionar serviço PostgreSQL compatível com produção, executar `alembic upgrade head` em banco descartável e a suíte com `TEST_DATABASE_URL`; acrescentar cobertura para isolamento de usuário, constraints, reconciliação e operações concorrentes. Manter SQLite apenas se continuar útil para testes rápidos.

**Resultado:** `alembic upgrade head`, `alembic check`, pytest PostgreSQL e `pip-audit` passaram no job API do run `38317703475`, SHA implantado `41368d93bd96c4e1814890d29110323fbec5e864`.

**Referências:** [quality.yml](../.github/workflows/quality.yml), [fixture de testes](../apps/api/tests/conftest.py), [README — execução contra PostgreSQL](../README.md), [README — migrations](../README.md).

### P1.5 Integrar E2E ao CI e acrescentar alguns fluxos integrados

**Evidência/resultado:** antes desta rodada, `test:e2e` não rodava na CI e a suíte usava mocks. O workflow inicia API e PostgreSQL descartáveis, aplica migrations e roda Playwright. O cenário integrado cobre setup com MFA fictício de CI, login, conta/categoria, despesa e retry, transferência e retry, compra no cartão e retry, pagamento de fatura e retry. A correção acrescentou criação e exclusão de usuário sintético autenticada pelo proprietário; a suíte mockada também cobre criação e exclusão pela interface. O workflow integrado e as regressões passaram no job Frontend do run `38317703475`, associado ao SHA implantado `41368d93bd96c4e1814890d29110323fbec5e864`.

**Resultado da validação:** o workflow passou nos três jobs no SHA implantado `41368d93bd96c4e1814890d29110323fbec5e864`, run `38317703475`; PostgreSQL 17, Alembic e Playwright integrado foram confirmados nesse SHA. O fluxo usa conta e dados exclusivamente sintéticos e testa autorização do proprietário, bloqueio de não proprietário e preservação de dados.

**Ação restante:** nenhuma pendência P1 de CI/E2E. Expandir navegação real e Safari iOS permanece como P2. Os cenários integrados usam somente dados sintéticos.

**Referências:** [package.json](../apps/web/package.json), [quality.yml — frontend](../.github/workflows/quality.yml), [spec E2E](../apps/web/e2e/finance-flows.spec.ts), [mocks E2E](../apps/web/e2e/api-mocks.ts).

### P1.6 Definir o gate de deploy e manter documentação operacional sincronizada

**Evidência:** na auditoria inicial, o SHA antigo `542f69e` falhava na API. A causa foi reproduzida e corrigida. A CI identificou também uma asserção dependente da precisão temporal e, depois, uma falha real de recuperação de sessão em operação concorrente; ambas foram corrigidas antes da publicação. Os três jobs passaram no SHA implantado `41368d93bd96c4e1814890d29110323fbec5e864` (run `38317703475`). O deploy segue manual, sem workflow de release/deploy automatizado. A regra Cloudflare recomendada foi criada e validada no painel em 12/10/2026.

**Resultado final:** o gate no SHA exato, checklist e procedimento manual foram seguidos. A VM foi atualizada no SHA verde, a migration `0018` e health checks foram confirmados. Atualização de 12/10/2026: o ruleset `24959980` exige PR e os três checks antes de atualizar `main`, sem aprovação humana.

**Referências:** [deployment.md — checklist](deployment.md), [deployment.md — health e rollback](deployment.md), [deployment.md — rate limit](deployment.md), [quality.yml](../.github/workflows/quality.yml).

### P1.7 Restaurar gestão de contas pelo proprietário e concluir rate limiting

**Estado final:** o proprietário esclareceu que contas de login adicionais devem ser permitidas somente quando criadas por ele. A regressão foi corrigida e implantada: somente o proprietário administra; o próprio proprietário não pode ser excluído, e qualquer registro pessoal/financeiro bloqueia a exclusão com `409`. A exclusão permitida remove somente sessões e o usuário vazio. A conta mencionada e dados de produção não foram consultados nem alterados. O limitador local recebe o IP encaminhado pelo cabeçalho dedicado que Caddy substitui e a API valida o endereço. Na Cloudflare, uma regra ativa agrega por IP os POSTs de login, bootstrap e pareamento MFA no host financeiro e bloqueia por 10 s após 20 requisições/10 s.

**Registro histórico de 12/10/2026, antes desta implementação local:** a administração de contas e o rate limit estavam implantados e a regra Cloudflare estava ativa; MFA individual ainda era uma pendência P2. A implementação posterior está descrita em P1.9 e segue pendente de CI/deploy. Acompanhar eventos/falsos positivos após uso real continua P2.

**Referências:** [managed_users.py](../apps/api/app/managed_users.py), [testes de gestão e preservação](../apps/api/tests/test_managed_users.py), [deployment.md — contas gerenciadas](deployment.md), [revisão de segurança — rate limit](revisao-geral-ux-seguranca-2026-10.md).

### P1.8 Inspecionar VM e fechar os controles operacionais com acesso direto

**Estado atual:** inspeção por SSH concluída com host key validada e sem abrir registros financeiros. Na inspeção original, a VM Debian 13 estava no SHA `542f69e` e Alembic `0016_totp_replay`. Por autorização expressa, foi instalada uma chave Ed25519 dedicada em `/root/.ssh/authorized_keys`; `PermitRootLogin without-password`, `PasswordAuthentication yes`, `PubkeyAuthentication yes`, `KbdInteractiveAuthentication no` e `AllowUsers sophia`/`root` foram conferidos por `sshd -T`; o serviço `ssh` permanece ativo. `sophia` mantém autenticação por senha e o proprietário pode usar `su -`; TCP/22 permanece aberto. A senha não foi lida nem enviada pelo chat. A VM está no SHA `41368d93bd96c4e1814890d29110323fbec5e864`, Alembic `0018_idempotency_tombstones (head)`, seis serviços ativos e health checks públicos verdes. A camada de rede anterior à VM e a instalação Proxmox não foram acessadas diretamente.

**Resultado final:** deploy e migration executados após CI verde; seis serviços, Alembic e endpoints públicos foram conferidos. Antes da migration, um dump temporário em modo `0600` foi validado por cabeçalho/lista e removido após os health checks. Seguem sem evidência direta o firewall/roteador anterior à VM e os jobs/retention/restore drill do Proxmox.

**Referências:** [deployment.md — verificação de serviços](deployment.md), [deployment.md — estado Alembic](deployment.md), [revisão — firewall/SSH](revisao-geral-ux-seguranca-2026-10.md), [README de infra](../infra/README.md).

## Prioridade P2 — aberta

| Item | Evidência inicial e recomendação | Referências |
|---|---|---|
| Ciclo de vida da chave MFA | MFA por conta foi implementado localmente, mas backups da base não recuperam os segredos sem `MFA_ENCRYPTION_KEY`. Manter uma cópia independente e protegida, testar restauração e definir procedimento de rotação com re-cifragem; nunca substituir a chave sem re-cifrar os segredos. Perda exige configurar uma chave nova e resetar/re-parear cada conta gerenciada; o reset preserva dados financeiros. | [config.py](../apps/api/app/config.py), [auth.py](../apps/api/app/auth.py), [deployment.md — chave MFA](deployment.md) |
| UX móvel, tipografia e densidade | Implementação local: aumentada a legibilidade das tabelas e preservado o layout responsivo em 390 px/820 px. Revisar em dispositivo real; CI e verificação física ainda pendentes. | [editorial-design.css](../apps/web/src/app/editorial-design.css), [finance-workspace.tsx](../apps/web/src/components/finance-workspace.tsx) |
| Landmarks e seção ativa | Implementação local: removido `<main>` redundante no workspace embutido, adicionado link de salto, estado da navegação (`aria-current`) e foco visível. CI ainda pendente. | [assistant-workspace.tsx](../apps/web/src/components/assistant-workspace.tsx) |
| URL, voltar/avançar e deep links | Implementação local: áreas e seções têm URL direta e navegam com voltar/avançar; a suíte E2E mockada cobre os caminhos. CI ainda pendente. | [assistant-workspace.tsx](../apps/web/src/components/assistant-workspace.tsx), [finance-flows.spec.ts](../apps/web/e2e/finance-flows.spec.ts) |
| Recuperação contextual de erros | Implementação local: falha da carga agrupada exibe retry contextual; erros de mutação não oferecem ação de retry que possa duplicar a operação. CI ainda pendente. | [finance-workspace.tsx](../apps/web/src/components/finance-workspace.tsx), [finance-flows.spec.ts](../apps/web/e2e/finance-flows.spec.ts) |
| Paginação e custo de consulta | Implementação local: transações usam cursor estável no servidor, limite explícito e filtros preservados; consultas de faturas carregam transações em lote para evitar N+1. Migration `0020_transaction_cursor_index` está somente no checkout; CI PostgreSQL e deploy pendentes. | [transactions.py](../apps/api/app/transactions.py), [finance_views.py](../apps/api/app/finance_views.py), [cards.py](../apps/api/app/cards.py) |
| Crescimento do ledger de idempotência | O ledger mantém chaves e fingerprints mínimos até a exclusão da conta, sem prazo de expiração, para impedir duplicidade após exclusão de movimento. Monitorar volume; qualquer retenção/expurgo futuro precisa preservar a garantia de replay e não incluir corpo de pedido. | [financial-rules.md](financial-rules.md), [database.md](database.md) |
| Política de alteração de fechamento/vencimento | Mudança da configuração do cartão pode aplicar a regra nova a compras futuras sem política de vigência/preview para ciclo. Definir data efetiva, mostrar impacto e cobrir meses curtos e fronteiras. | [cards.py](../apps/api/app/cards.py), [invoices.py](../apps/api/app/invoices.py), [finance_engine.py](../apps/api/app/finance_engine.py) |
| CSP | Cabeçalho observado permite `'unsafe-inline'` em `script-src` e `style-src`. Avaliar nonce/hash compatível com Next.js, primeiro em modo report-only/ambiente controlado, e remover exceção somente após validar hidratação e fluxos. Não há XSS confirmado. | [Caddyfile](../infra/Caddyfile), [revisão anterior](revisao-geral-ux-seguranca-2026-10.md) |
| Estorno explícito de ocorrência paga | O P1.2 bloqueia edição/exclusão genérica de transação de ocorrência paga com `409`, preservando o histórico. Se o produto precisar corrigir esses registros, definir depois um fluxo explícito de estorno/cancelamento, com reconciliação e trilha de auditoria. | [financial-rules.md](financial-rules.md), [transactions.py](../apps/api/app/transactions.py), [test_recurrences.py](../apps/api/tests/test_recurrences.py) |
| Actions Node 20 | Implementação local: `actions/checkout` v7.0.1, `actions/setup-node` v7.1.0 e `actions/setup-python` v7.0.0 fixadas por SHA. A execução de CI desta alteração ainda está pendente. | [quality.yml](../.github/workflows/quality.yml), [guia de actions do GitHub](https://github.blog/changelog/2026-09-23-node-20-is-no-longer-available-in-github-actions/) |
| Backups, recuperação e RPO/RTO | Há declarações documentais diferentes: confirmação de backup/restauração em deployment e pedido de validação no README de infraestrutura. Registrar evidência, escopo, data do último restore drill, RPO/RTO, criptografia e responsável, confirmando no Proxmox diretamente. | [deployment.md](deployment.md), [infra README](../infra/README.md) |
| E-mail proprietário no código | A política de MFA ainda identifica o único proprietário por endereço fixo no código público. Avaliar configuração não secreta de identidade (sem enfraquecer MFA) e reduzir exposição de dado pessoal no repositório. | [auth.py](../apps/api/app/auth.py), [deployment.md](deployment.md) |
| GitHub settings | Concluído em 12/10/2026: ruleset `24959980` ativo em `refs/heads/main`. Exige PR e checks `API`, `Frontend` e `Imagens e perfil público` atualizados em relação à base, sem aprovação humana; não permite apagar ou forçar push e não tem bypass actors. A primeira execução após a criação deve confirmar os contextos no commit do PR. | [quality.yml](../.github/workflows/quality.yml), [deployment.md — gate de PR e deploy](deployment.md), [ruleset no GitHub](https://github.com/vitokkkj/finance-ai/settings/rules) |
| Cobertura de navegador e dispositivos | Implementação local acrescenta no E2E integrado pareamento de conta gerenciada, login posterior, reset pelo painel do proprietário e exclusão da conta sintética; expiração permanece coberta na API. A nova execução CI ainda está pendente. Continuam abertas baixa de compromisso, pagamento parcial/total, upload de imagem, tema, gestos e Safari iOS; validar também iPhone real (safe area, teclado e PWA). | [integrated-finance.spec.ts](../apps/web/e2e/integrated-finance.spec.ts), [testes gerenciados](../apps/api/tests/test_managed_users.py), [revisão — telas reais](revisao-geral-ux-seguranca-2026-10.md) |
| Histórico de recorrências | Lista cobre horizonte móvel materializado de 90 dias; ocorrências fora do horizonte não são pesquisáveis como histórico integral. Definir busca/histórico conforme necessidade de produto, sem materialização ilimitada. | [revisão anterior](revisao-geral-ux-seguranca-2026-10.md), [recurrences.py](../apps/api/app/recurrences.py) |
| Alertas externos | Centro de avisos só funciona com app aberto; push/e-mail não implementados. Decidir depois de confiabilidade: push opt-in iniciado pelo usuário, links diretos e política de privacidade. | [README](../README.md), [revisão anterior](revisao-geral-ux-seguranca-2026-10.md) |

## Prioridade P3 — aberta

| Item | Proposta | Limites e fontes |
|---|---|---|
| Relatórios financeiros | Relatórios mensais por categoria, período e conta, com tendências e navegação até os lançamentos de origem. Todos os agregados devem vir do Finance Engine/PostgreSQL e manter semântica de transferências, pagamentos e reembolsos. | Aplicar depois de reconciliação, PostgreSQL CI e paginação. Padrão de relatórios documentado pelo [YNAB](https://www.ynab.com/blog/ynab-reports-and-data). |
| Metas | Metas opcionais com progresso visível, ligadas a contas/categorias quando houver demanda, sem criar cálculos financeiros no frontend nem tabelas antecipadas sem modelo concreto. | Considerar depois de relatórios e feedback do uso. Exemplo de acompanhamento de metas: [YNAB Goal Tracking](https://www.ynab.com/features/goal-tracking). |
| Importação bancária/OFX e Open Finance | Primeiro melhorar importação manual com arquivo de exemplo, mapeamento de colunas, revisão de duplicidade e desfazer. Decidir OFX antes de ampliar formato. Pluggy exige documentação oficial atual, escopos somente leitura, consentimento/expiração, IDs externos, sincronização idempotente, deduplicação e reconciliação. Nunca armazenar senha bancária. | Não há integração bancária implementada. [integrações.md](integrations.md), [README — capacidades futuras](../README.md). A conciliação com revisão antes de confirmar é um padrão de produto possível, não evidência de requisito já implementado: [Organizze](https://ajuda.organizze.com.br/hc/pt-br/articles/5994220061203-Web-Lan%C3%A7amentos-Concilia%C3%A7%C3%A3o-banc%C3%A1ria). |
| Investimentos, parcelamentos e financiamentos | Documentar domínio futuro e regras necessárias; só implementar na fase apropriada, com valores decimais, calendário e reconciliação. | README registra esses domínios como não implementados: [README](../README.md). |

## Limites e pendências que seguem abertos

1. **Rede anterior à VM:** o firewall local, o SSH e o túnel foram conferidos, mas roteador/firewall antes da VM e exposição direta do TCP/22 fora da rede overlay não foram verificados.
2. **Proxmox:** o proprietário confirmou backup criptografado e restauração testada em 12/10/2026; falta evidência direta recente de jobs, retenção e restore drill. O dump temporário pré-deploy foi validado e removido, sem substituir o backup operacional.
3. **Ruleset GitHub:** `24959980` está ativo e sem bypass; o PR atual confirmará os três checks requeridos (`API`, `Frontend`, `Imagens e perfil público`) após a execução da CI.
4. **Dados reais:** a revisão visual da interface não reproduz nomes, saldos ou transações do usuário no relatório. Testes permanecem com dados sintéticos.
5. **Observação e capacidade do limitador:** acompanhar eventos e falsos positivos após uso real. O painel Free mostrava `1/1` regras de rate limit ocupadas em 12/10/2026; consolide futuras rotas na regra atual ou revise o plano antes de adicionar outra.

## Registro de execução deste plano

| Data | Item | Resultado/evidência |
|---|---|---|
| 12/10/2026 | Criação deste plano | Documento criado para preservar achados e prioridades. Na criação, nenhuma correção P1/P2/P3 foi marcada como concluída. |
| 12/10/2026 | Conta única (P1.7) | Provisionamento desabilitado em API/interface; um usuário na VM confirmado sem identificar a conta; testes e documentos atualizados. |
| 12/10/2026 | Rate limit (P1.7) | Caddy passa IP da Cloudflare por cabeçalho dedicado; API valida o IP; teste da origem encaminhada passou. Regras de borda Cloudflare não verificadas. |
| 12/10/2026 | VM/SSH (P1.8) | Inspeção direta; TCP/22 mantido aberto; senha e chave disponíveis para `sophia`, login SSH de `root` desativado e elevação documentada com `su -`. O serviço foi reiniciado pelo systemd após falha no reload, ficou ativo e a nova conexão como `sophia` passou. Firewall upstream e Proxmox não consultados. |
| 12/10/2026 | Finance Engine (P1.2/P1.3) | Reconciliação de compra paga protegida, ocorrência paga bloqueada para edição/exclusão genérica e idempotência persistente implantada. `0018_idempotency_tombstones` mantém chave após excluir movimento; regressões API e corrida PostgreSQL passaram. |
| 12/10/2026 | CI/E2E (P1.1/P1.4/P1.5) | A CI PostgreSQL `38317703475` passou nos jobs API, Frontend/E2E e imagens/runtime. O run intermediário `38317180381` encontrou uma falha na recuperação após conflito concorrente; o UUID passou a ser capturado antes da gravação e o SHA corrigido foi aprovado. |
| 12/10/2026 | Gate de deploy (P1.6) | A CI verde para o SHA exato `41368d9` foi usada como gate manual; o deploy autorizado foi concluído e documentado. Branch protection continua P2. |
| 12/10/2026 | CI hospedada e integração em `main` | Run `38306602486` passou nos jobs API, Frontend e runtime no SHA de implementação `a150afe213fe2910fa9798dfe76e87abf50699dc`; migration PostgreSQL 17, suíte completa, E2E integrado, auditorias e builds passaram. O relatório foi atualizado e o SHA final `e45e94922132d896afcddcbfae1d55e98f5cccda` também passou nos três jobs no run `38306907130`. `main` atualizado; VM segue no SHA antigo aguardando operação privilegiada por `su -` do proprietário. |
| 12/10/2026 | Gestão segura de usuários (P1.7) | A rota e a interface de administração foram restauradas para o proprietário; exclusão bloqueia usuários com dados e nunca permite remover o proprietário. CI identificou e corrigiu uma asserção temporal; SHA final `01488a4`, run `38312160754` verde. Conta citada pelo usuário não foi consultada ou excluída. |
| 12/10/2026 | Deploy na VM e migration (P1.2/P1.3/P1.8) | SHA `01488a4` aplicado em `/opt/sophia-test`; migration `0017_financial_idempotency` confirmada. Seis serviços ativos, health live/ready 200 e endpoints sem sessão 401. Houve 502 transitório durante inicialização do frontend, resolvido antes da checagem final. Dump temporário validado antes da migration e removido depois. |
| 12/10/2026 | Idempotência e deploy final (P1.1/P1.2/P1.3/P1.4/P1.5/P1.6/P1.8) | SHA `41368d93bd96c4e1814890d29110323fbec5e864`, run `38317703475` verde; `0018_idempotency_tombstones (head)`. Seis serviços ativos, health live/ready 200, rotas protegidas 401, `/api/docs` 404, cabeçalhos de segurança conferidos, portas internas sem bindings de host. Dump custom `0600` validado no container PostgreSQL e removido. SSH ativo conforme a política do proprietário. |
| 12/10/2026 | Cloudflare (P1.7) | Regra ativa por IP, limitada ao host `finance.ruralflow.com.br` e POSTs de setup/login/MFA: 20 requisições em 10 segundos, bloqueio de 10 segundos. Expressão validada; 0 eventos na checagem; não houve teste de bloqueio na produção. |
| 12/10/2026 | SSH e autorização de deploy (P1.8) | O proprietário manteve SSH/22 e senha de `sophia`, com elevação via `su -`, e autorizou deploys quando necessários. A chave root dedicada foi validada; chave privada fora do Git. |
| 12/10/2026 | Documentação de infraestrutura | Corrigido `infra/README.md` para identificar `docker-compose.vm.yml` como perfil de produção e esclarecer que `sophia-test` é um nome operacional histórico, não um ambiente descartável. |
| 12/10/2026 | Continuação P1/P2 no checkout | MFA TOTP individual obrigatório e cursor de transações (`0019`/`0020`) implementados localmente; integrado E2E acrescentado para pareamento, login e reset pelo proprietário. UX, acessibilidade, URLs, retry, lote de faturas e pins das Actions atualizados. Verificações locais: API 203 passaram/3 ignorados, Ruff, mypy, typecheck, build e 22 Playwright mockados passaram; Alembic tem um único head `0020`. Docker/PostgreSQL não estão disponíveis nesta máquina; CI, backup separado da chave Fernet e deploy ainda pendentes. Quatro avisos de Biome em `!important` e dois avisos de depreciação Starlette permanecem. |
| 12/10/2026 | Governança GitHub P2 | O proprietário escolheu PR + CI verde, sem aprovação humana. Ruleset ativo `24959980` protege `refs/heads/main`: checks `API`, `Frontend`, `Imagens e perfil público` estritos, sem bypass, exclusão ou force-push. A CI do PR atual ainda deve confirmar os contextos. |

Atualizar esta tabela e as prioridades somente após mudança verificável e checagens correspondentes. Atualizar a documentação operacional junto com cada mudança, incluindo limitações, falhas e comandos de verificação pendentes.
