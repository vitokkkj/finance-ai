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

**Código e CI:** a correção de gestão de contas foi integrada em `main` no SHA `c81f95bd98d09382c9666afd1ac206331b86dd39`. A CI desse SHA identificou uma asserção de ordem de timestamps dependente da precisão do banco; o teste foi corrigido para comparar os registros como conjunto. O SHA final de aplicação é `01488a4c161fedac7444d1885b2b0b177a2bd546`; os três jobs passaram na [execução 38312160754](https://github.com/vitokkkj/finance-ai/actions/runs/38312160754): API com PostgreSQL 17 (193 testes), Frontend/Playwright (20 testes) e imagens/runtime. A VM executa esse SHA; uma atualização posterior apenas documental não altera o código implantado.

**Contas de login:** o proprietário confirmou que contas adicionais são usuários de login do app e devem poder ser criadas somente por ele. A aplicação permite listar/criar/excluir contas gerenciadas apenas na área do proprietário, mantém cadastro público desabilitado e recusa `DELETE` do próprio proprietário ou de usuário com dados associados (`409`). A criação/exclusão E2E usa conta sintética. A conta mencionada pelo proprietário e os dados reais não foram consultados nem excluídos. MFA individual para contas gerenciadas continua P2.

**Deploy e banco:** com autorização do proprietário, o commit `01488a4c161fedac7444d1885b2b0b177a2bd546` foi publicado na VM depois de CI verde. A migration `0017_financial_idempotency` foi aplicada e confirmada como head. Os seis serviços Compose estão ativos; API, web e PostgreSQL estão saudáveis. Health live/ready retornam `200`, e `/api/accounts` e `/api/admin/users`, sem sessão, retornam `401`; `/api/docs` retorna `404`. A API e o banco não publicam portas no host. Durante a recriação de containers houve uma janela transitória de `502` porque o frontend ainda iniciava; os checks públicos repetidos depois retornaram `200` e o erro não persistiu.

**Backup pré-deploy:** foi criado um dump PostgreSQL temporário em formato custom, modo `0600`, sem criptografia. O cabeçalho e a listagem de restauração passaram na validação sem abrir registros; depois do deploy e dos health checks, o arquivo foi removido e sua ausência confirmada. O proprietário confirmou backup criptografado e restore testado no Proxmox; não houve inspeção direta dos jobs, retenção ou restore drill nessa execução. Não foram lidos `.env`, tokens, e-mails, transações nem saldos.

**Cloudflare:** a regra **Autenticacao - limite por IP** foi ativada na zona, somente para `finance.ruralflow.com.br`, `POST` e as rotas de setup, verificação/login e pareamento MFA. O teto é 20 requisições por IP em 10 segundos; o bloqueio dura 10 segundos. O painel validou a expressão e mostrou status ativo, com zero eventos no instante da conferência. Não foi provocado bloqueio de teste em produção. O limite da API por conta e IP continua ativo como proteção adicional.

**SSH:** TCP/22 permanece acessível conforme escolha do proprietário. `sophia` mantém senha e chave e pode usar `su -`; root aceita somente chave pública. `sshd -T` confirmou `PasswordAuthentication yes`, `PermitRootLogin without-password` (equivalente a `prohibit-password`) e `AllowUsers sophia root`. O daemon SSH está ativo; a chave Ed25519 dedicada foi testada com login root e permanece fora do repositório. A rede anterior à VM não foi inspecionada.

| P1 | Situação final |
|---|---|
| 1.1 — CI | Corrigida; três jobs verdes no SHA aplicado `01488a4` (run `38312160754`). A falha intermediária `38311894511` foi causada por ordenação/precisão temporal de SQLite e corrigida no commit final. |
| 1.2 — reconciliação financeira | Regras para compra paga e ocorrência paga protegidas, com regressões cobertas; código implantado. |
| 1.3 — idempotência | Lançamentos, transferências, compras e pagamentos persistem chave por usuário/operação; retries repetem o resultado e payload distinto retorna `409`. Migration `0017` aplicada na VM. |
| 1.4 — PostgreSQL na CI | PostgreSQL 17, `alembic upgrade head`, `alembic check`, suíte de API e auditoria de dependências passaram no CI final. |
| 1.5 — E2E | 20 testes Playwright passaram no CI; incluem gestão sintética de usuários pelo proprietário e fluxos financeiros integrados. |
| 1.6 — gate e documentação de deploy | CI verde exigida no SHA exato; deploy manual documentado e executado no SHA verificado. Branch protection continua P2. |
| 1.7 — contas e rate limit | Administração segura de usuários implantada; regra de borda Cloudflare criada e ativa. MFA individual de contas adicionais continua P2. |
| 1.8 — VM | Inspeção, atualização e migration concluídas. Todos os serviços ativos e endpoints públicos verificados; caminho de rede anterior à VM e evidência direta do Proxmox continuam sem validação independente. |

**VM:** Debian 13; o checkout está no SHA `01488a4`; Alembic `0017_financial_idempotency (head)`; seis serviços ativos. Na última verificação havia 8,6 GB livres de 40 GB (77% usados). A inspeção original registrou 7,3/8 GB de RAM livres; essa medição não foi repetida. A contagem de usuários da inspeção inicial é histórica e não foi repetida; nenhum registro de Richard foi lido.

**Falhas e limitações remanescentes:** houve um CI intermediário vermelho por causa da asserção temporal, já corrigido e seguido de CI verde; houve `502` transitório na inicialização do frontend durante deploy, resolvido e seguido de health checks públicos verdes. O reload inicial do SSH falhou por ativação por socket; o serviço foi iniciado, `sshd -t` passou e o login por chave root funcionou. O serviço Docker não é acessível pela conta `sophia` sem privilégio, por desenho. O Docker Desktop local estava indisponível; a CI executou builds/imagens e migrations em Linux/PostgreSQL. O lint tem quatro avisos existentes de `!important` na regra `prefers-reduced-motion`. A CI não encontrou vulnerabilidades em `npm audit` nem `pip-audit`. Os avisos de actions Node 20 e a ausência de proteção de `main` permanecem no backlog P2.

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

## Prioridade P1 — resultados e evidências de conclusão

Os itens P1 abaixo são acompanhados por evidência e estado de código/VM. Uma correção local ou CI verde não equivale a deploy; a versão publicada só é considerada atualizada após verificar SHA, migration, serviços e health checks.

### P1.1 Corrigir e tornar verde a validação do SHA implantável

**Evidência:** a execução #47 para `542f69e` falhou no job API. O workflow combina Ruff, checagem de tipos e pytest em uma etapa, então o resumo público não identifica qual deles falhou; `pip-audit` fica condicionado ao sucesso anterior. O mesmo job foi reportado como falho nas execuções #46 e #44.

**Ação:** obter logs autenticados, identificar e corrigir a causa, separar etapas para diagnóstico útil e exigir uma execução verde para o SHA candidato a deploy. Documentar o SHA validado e a relação entre aprovação de CI e deploy manual.

**Resultado:** causa corrigida; API, Frontend e runtime passaram no run [38305965616](https://github.com/vitokkkj/finance-ai/actions/runs/38305965616), SHA `63eee3cb990efe0c87958d13c35effa3ac2cb77b`.

**Referências:** [quality.yml](../.github/workflows/quality.yml), [quality.yml — auditoria Python](../.github/workflows/quality.yml), [deployment.md — deploy manual](deployment.md).

### P1.2 Preservar reconciliação ao editar/excluir compras e ocorrências pagas

**Evidência:** exclusão de transações ligadas a faturas ou recorrências é tratada em `finance_deletion.py`; os totais de fatura limitam saldo em aberto a zero (`max(total - pago, 0)`). A edição genérica impede apenas vínculo a compromisso planejado; não bloqueia de forma equivalente transação gerada por ocorrência de recorrência já paga. Isso pode deixar pagamentos acima das compras da fatura ou valores realizados divergentes da ocorrência original.

**Ação:** impedir exclusão/redução de compras que já tenham pagamentos associados, ou oferecer operações explícitas e auditáveis de estorno/crédito/chargeback; impedir edição de transação de ocorrência paga ou atualizar atomicamente o vínculo e os valores da ocorrência. Definir política de cancelamento versus remoção de histórico e cobrir saldos, pagamentos parciais/totais, recorrência e reconciliação com testes.

**Atualização da implementação:** a compra individual continua bloqueada se sua exclusão fizer pagamentos excederem o total restante. Regressões locais agora cobrem compra parcialmente paga, totalmente paga e compra cuja exclusão é permitida porque outra mantém cobertura; também confirmam que a exclusão explícita da fatura reverte o saldo da conta e apaga compras/pagamentos conforme o aviso de confirmação. Deploy aguarda CI PostgreSQL verde.

**Referências:** [finance_deletion.py](../apps/api/app/finance_deletion.py), [finance_engine.py](../apps/api/app/finance_engine.py), [transactions.py — edição](../apps/api/app/transactions.py), [recurrences.py — baixa](../apps/api/app/recurrences.py), [financial-rules.md](financial-rules.md).

### P1.3 Adicionar idempotência a operações financeiras repetíveis

**Evidência:** os endpoints de criação de transferência, lançamento e pagamento/criação de compra não apresentam chave de idempotência. Repetição após timeout ou retry pode criar mais de um registro; deduplicação por valor/data não é segura, pois movimentos iguais podem ser legítimos.

**Ação:** aceitar chave de idempotência ligada ao usuário autenticado, operação e payload; persistir resultado de forma transacional e definir prazo/retorno para replay. Cobrir timeout/retry concorrente e rejeitar reutilização da chave com payload diferente.

**Atualização da implementação:** a migration `0018_idempotency_tombstones` conserva os fingerprints e IDs das operações depois da exclusão de movimentos; repetição com payload igual retorna `410`, e payload diferente retorna `409`. A política atual mantém metadados mínimos enquanto a conta existir, sem expiração, e o chat/frontend reutiliza uma chave estável durante retries. Testes locais cobrem lançamento, transferência, compra de cartão, pagamento, exclusão e retry; o teste de concorrência e a migration PostgreSQL precisam passar na CI antes do deploy.

**Referências:** [transfers.py](../apps/api/app/transfers.py), [transactions.py](../apps/api/app/transactions.py), [invoices.py — compra](../apps/api/app/invoices.py), [invoices.py — pagamento](../apps/api/app/invoices.py).

### P1.4 Exercitar PostgreSQL e Alembic na CI

**Evidência:** a configuração CI usa SQLite em memória. A fixture cria tabelas com `Base.metadata.create_all`; não percorre migrations PostgreSQL nem garante comportamento idêntico de chaves estrangeiras, locks ou concorrência.

**Ação:** adicionar serviço PostgreSQL compatível com produção, executar `alembic upgrade head` em banco descartável e a suíte com `TEST_DATABASE_URL`; acrescentar cobertura para isolamento de usuário, constraints, reconciliação e operações concorrentes. Manter SQLite apenas se continuar útil para testes rápidos.

**Resultado:** `alembic upgrade head`, `alembic check`, pytest PostgreSQL e `pip-audit` passaram no job API hospedado do run `38305965616`.

**Referências:** [quality.yml](../.github/workflows/quality.yml), [fixture de testes](../apps/api/tests/conftest.py), [README — execução contra PostgreSQL](../README.md), [README — migrations](../README.md).

### P1.5 Integrar E2E ao CI e acrescentar alguns fluxos integrados

**Evidência/resultado:** antes desta rodada, `test:e2e` não rodava na CI e a suíte usava mocks. O workflow inicia API e PostgreSQL descartáveis, aplica migrations e roda Playwright. O cenário integrado cobre setup com MFA fictício de CI, login, conta/categoria, despesa e retry, transferência e retry, compra no cartão e retry, pagamento de fatura e retry. A correção acrescentou criação e exclusão de usuário sintético autenticada pelo proprietário; a suíte mockada também cobre criação e exclusão pela interface. O CI final passou com 20 testes Playwright no SHA implantado `01488a4c161fedac7444d1885b2b0b177a2bd546` (run `38312160754`).

**Resultado da validação:** o workflow passou nos três jobs no SHA implantado `01488a4c161fedac7444d1885b2b0b177a2bd546`, run `38312160754`; PostgreSQL 17, Alembic e Playwright integrado foram confirmados nesse SHA. O fluxo novo usa conta e dados exclusivamente sintéticos e testa autorização do proprietário, bloqueio de não proprietário e preservação de dados.

**Ação restante:** nenhuma pendência P1 de CI/E2E. Expandir navegação real e Safari iOS permanece como P2. Os cenários integrados usam somente dados sintéticos.

**Referências:** [package.json](../apps/web/package.json), [quality.yml — frontend](../.github/workflows/quality.yml), [spec E2E](../apps/web/e2e/finance-flows.spec.ts), [mocks E2E](../apps/web/e2e/api-mocks.ts).

### P1.6 Definir o gate de deploy e manter documentação operacional sincronizada

**Evidência:** na auditoria inicial, o SHA antigo `542f69e` falhava na API. A causa foi reproduzida e corrigida. A CI também encontrou uma asserção dependente da ordenação/precisão temporal no SHA `c81f95b`; após a correção, os três jobs passaram no SHA implantado `01488a4` (run `38312160754`). O deploy segue manual, sem workflow de release/deploy automatizado. A regra Cloudflare recomendada foi criada e validada no painel em 12/10/2026.

**Resultado final:** o gate no SHA exato, checklist e procedimento manual foram seguidos. A VM foi atualizada no SHA de CI verde, a migration e health checks foram confirmados. `main` não tem branch protection nem rulesets; isso permanece P2.

**Referências:** [deployment.md — checklist](deployment.md), [deployment.md — health e rollback](deployment.md), [deployment.md — rate limit](deployment.md), [quality.yml](../.github/workflows/quality.yml).

### P1.7 Restaurar gestão de contas pelo proprietário e concluir rate limiting

**Estado final:** o proprietário esclareceu que contas de login adicionais devem ser permitidas somente quando criadas por ele. A regressão foi corrigida e implantada: somente o proprietário administra; o próprio proprietário não pode ser excluído, e qualquer registro pessoal/financeiro bloqueia a exclusão com `409`. A exclusão permitida remove somente sessões e o usuário vazio. A conta mencionada e dados de produção não foram consultados nem alterados. O limitador local recebe o IP encaminhado pelo cabeçalho dedicado que Caddy substitui e a API valida o endereço. Na Cloudflare, uma regra ativa agrega por IP os POSTs de login, bootstrap e pareamento MFA no host financeiro e bloqueia por 10 s após 20 requisições/10 s.

**Ação restante:** acompanhar eventos e falsos positivos da regra Cloudflare após uso real. Contas gerenciadas ainda usam senha sem MFA individual; inscrição e recuperação de MFA por usuário ficam como P2.

**Referências:** [managed_users.py](../apps/api/app/managed_users.py), [testes de gestão e preservação](../apps/api/tests/test_managed_users.py), [deployment.md — contas gerenciadas](deployment.md), [revisão de segurança — rate limit](revisao-geral-ux-seguranca-2026-10.md).

### P1.8 Inspecionar VM e fechar os controles operacionais com acesso direto

**Estado atual:** inspeção por SSH concluída com host key validada e sem abrir registros financeiros. Na inspeção original, a VM Debian 13 estava no SHA `542f69e` e Alembic `0016_totp_replay`. Por autorização expressa, foi instalada uma chave Ed25519 dedicada em `/root/.ssh/authorized_keys`; `PermitRootLogin prohibit-password` e `AllowUsers sophia root` foram conferidos por `sshd -T`, o serviço `ssh` está ativo e a conexão como `root` foi validada. `sophia` mantém autenticação por senha e chave; TCP/22 permanece aberto e o proprietário pode continuar usando `su -`. A senha não foi lida nem enviada pelo chat. A VM está agora no SHA `01488a4`, Alembic `0017_financial_idempotency (head)`, seis serviços ativos e health checks públicos verdes. A camada de rede anterior à VM e a instalação Proxmox não foram acessadas diretamente.

**Resultado final:** deploy e migration executados após CI verde; seis serviços, Alembic e endpoints públicos foram conferidos. Antes da migration, um dump temporário em modo `0600` foi validado por cabeçalho/lista e removido após os health checks. Seguem sem evidência direta o firewall/roteador anterior à VM e os jobs/retention/restore drill do Proxmox.

**Referências:** [deployment.md — verificação de serviços](deployment.md), [deployment.md — estado Alembic](deployment.md), [revisão — firewall/SSH](revisao-geral-ux-seguranca-2026-10.md), [README de infra](../infra/README.md).

## Prioridade P2 — aberta

| Item | Evidência inicial e recomendação | Referências |
|---|---|---|
| Contas gerenciadas e MFA individual | Contas adicionais atualmente usam senha sem MFA individual. Implementar inscrição TOTP por usuário, fluxo de recuperação com validação forte e revogação de sessões, sem reutilizar o segredo do proprietário. | [auth.py](../apps/api/app/auth.py), [deployment.md](deployment.md) |
| UX móvel, tipografia e densidade | Tabelas usam texto pequeno (há regra de 9 px) e o cabeçalho/filtros podem empurrar conteúdo; cartões exigem rolagem horizontal. Revisar hierarquia, alvos, tabela/cartão responsivo, contraste e primeira dobra em larguras reais sem perder consistência da identidade visual. | [editorial-design.css](../apps/web/src/app/editorial-design.css), [finance-workspace.tsx](../apps/web/src/components/finance-workspace.tsx) |
| Landmarks e seção ativa | Verificar estrutura de `<main>`, link de salto, nome/estado da navegação e foco/teclado. A auditoria identificou landmarks semânticos redundantes e ausência de sinalização suficientemente clara da seção ativa. | [assistant-workspace.tsx](../apps/web/src/components/assistant-workspace.tsx) |
| URL, voltar/avançar e deep links | Navegação entre áreas mantém a rota `/`; permitir URL direta para seção e sincronizar histórico de navegação, sem quebrar estado de sessão. | [assistant-workspace.tsx](../apps/web/src/components/assistant-workspace.tsx) |
| Recuperação contextual de erros | Falha em uma carga agrupada pode bloquear a tela sem recuperação por recurso. Distinguir erro de estado vazio, oferecer retry localizado e preservar o conteúdo já carregado. | [finance-workspace.tsx](../apps/web/src/components/finance-workspace.tsx) |
| Paginação e custo de consulta | API carrega o histórico sem limite; a paginação do frontend não reduz consulta. Visões de faturas carregam movimentos por fatura e produzem consultas repetidas/N+1. Implementar cursor no servidor e agregação/lote; medir antes de adicionar cache ou infraestrutura. | [transactions.py](../apps/api/app/transactions.py), [finance_views.py](../apps/api/app/finance_views.py), [cards.py](../apps/api/app/cards.py) |
| Crescimento do ledger de idempotência | O ledger mantém chaves e fingerprints mínimos até a exclusão da conta, sem prazo de expiração, para impedir duplicidade após exclusão de movimento. Monitorar volume; qualquer retenção/expurgo futuro precisa preservar a garantia de replay e não incluir corpo de pedido. | [financial-rules.md](financial-rules.md), [database.md](database.md) |
| Política de alteração de fechamento/vencimento | Mudança da configuração do cartão pode aplicar a regra nova a compras futuras sem política de vigência/preview para ciclo. Definir data efetiva, mostrar impacto e cobrir meses curtos e fronteiras. | [cards.py](../apps/api/app/cards.py), [invoices.py](../apps/api/app/invoices.py), [finance_engine.py](../apps/api/app/finance_engine.py) |
| CSP | Cabeçalho observado permite `'unsafe-inline'` em `script-src` e `style-src`. Avaliar nonce/hash compatível com Next.js, primeiro em modo report-only/ambiente controlado, e remover exceção somente após validar hidratação e fluxos. Não há XSS confirmado. | [Caddyfile](../infra/Caddyfile), [revisão anterior](revisao-geral-ux-seguranca-2026-10.md) |
| Estorno explícito de ocorrência paga | O P1.2 bloqueia edição/exclusão genérica de transação de ocorrência paga com `409`, preservando o histórico. Se o produto precisar corrigir esses registros, definir depois um fluxo explícito de estorno/cancelamento, com reconciliação e trilha de auditoria. | [financial-rules.md](financial-rules.md), [transactions.py](../apps/api/app/transactions.py), [test_recurrences.py](../apps/api/tests/test_recurrences.py) |
| Actions Node 20 | Execuções do GitHub reportaram avisos de actions em Node 20; a revisão anterior apontou atualização necessária para releases compatíveis com Node 24 mantendo pin por SHA. Validar cada action e compatibilidade no runner antes de atualizar. | [quality.yml](../.github/workflows/quality.yml), [guia de actions do GitHub](https://github.blog/changelog/2026-09-23-node-20-is-no-longer-available-in-github-actions/) |
| Backups, recuperação e RPO/RTO | Há declarações documentais diferentes: confirmação de backup/restauração em deployment e pedido de validação no README de infraestrutura. Registrar evidência, escopo, data do último restore drill, RPO/RTO, criptografia e responsável, confirmando no Proxmox diretamente. | [deployment.md](deployment.md), [infra README](../infra/README.md) |
| E-mail proprietário no código | A política de MFA ainda identifica o único proprietário por endereço fixo no código público. Avaliar configuração não secreta de identidade (sem enfraquecer MFA) e reduzir exposição de dado pessoal no repositório. | [auth.py](../apps/api/app/auth.py), [deployment.md](deployment.md) |
| GitHub settings | Consulta autenticada em 12/10/2026 confirmou que `main` não tem branch protection e que o repositório não possui rulesets (`[]`). A documentação exige CI verde no SHA como gate manual, mas isso não impede push direto. Definir proteção que exija `API`, `Frontend` e `Imagens e perfil público` após conferir os nomes no novo run; environments e revisão obrigatória seguem sem avaliação. | [quality.yml](../.github/workflows/quality.yml), [dependabot.yml](../.github/dependabot.yml), [deployment.md — gate manual](deployment.md) |
| Cobertura de navegador e dispositivos | Ampliar além dos mocks para login/MFA, baixa de compromisso, pagamento parcial/total, upload de imagem, tema, gestos e Safari iOS; validar iPhone real (safe area, teclado, PWA e gestos), pois Chromium em 390/820 px não comprova isso. | [revisão anterior](revisao-geral-ux-seguranca-2026-10.md), [revisão — telas reais](revisao-geral-ux-seguranca-2026-10.md) |
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
3. **Branch protection:** decidir e aplicar os checks requeridos em `main`; o estado atual sem proteção foi verificado.
4. **Dados reais:** a revisão visual da interface não reproduz nomes, saldos ou transações do usuário no relatório. Testes permanecem com dados sintéticos.
5. **Observação e capacidade do limitador:** acompanhar eventos e falsos positivos após uso real. O painel Free mostrava `1/1` regras de rate limit ocupadas em 12/10/2026; consolide futuras rotas na regra atual ou revise o plano antes de adicionar outra.

## Registro de execução deste plano

| Data | Item | Resultado/evidência |
|---|---|---|
| 12/10/2026 | Criação deste plano | Documento criado para preservar achados e prioridades. Na criação, nenhuma correção P1/P2/P3 foi marcada como concluída. |
| 12/10/2026 | Conta única (P1.7) | Provisionamento desabilitado em API/interface; um usuário na VM confirmado sem identificar a conta; testes e documentos atualizados. |
| 12/10/2026 | Rate limit (P1.7) | Caddy passa IP da Cloudflare por cabeçalho dedicado; API valida o IP; teste da origem encaminhada passou. Regras de borda Cloudflare não verificadas. |
| 12/10/2026 | VM/SSH (P1.8) | Inspeção direta; TCP/22 mantido aberto; senha e chave disponíveis para `sophia`, login SSH de `root` desativado e elevação documentada com `su -`. O serviço foi reiniciado pelo systemd após falha no reload, ficou ativo e a nova conexão como `sophia` passou. Firewall upstream e Proxmox não consultados. |
| 12/10/2026 | Finance Engine (P1.2/P1.3) | Reconciliação de compra paga protegida, ocorrência paga bloqueada para edição/exclusão genérica, idempotência persistente adicionada; regressões API passam. PostgreSQL 17 aguarda CI. |
| 12/10/2026 | CI/E2E (P1.1/P1.4/P1.5) | Causa reproduzida e workflow ampliado; nesse ponto do registro, a execução hospedada ainda aguardava publicação. |
| 12/10/2026 | Gate de deploy (P1.6) | CI verde no mesmo SHA documentada como gate manual; sem deploy automático e sem atualização da VM nesta rodada. |
| 12/10/2026 | CI hospedada e integração em `main` | Run `38306602486` passou nos jobs API, Frontend e runtime no SHA de implementação `a150afe213fe2910fa9798dfe76e87abf50699dc`; migration PostgreSQL 17, suíte completa, E2E integrado, auditorias e builds passaram. O relatório foi atualizado e o SHA final `e45e94922132d896afcddcbfae1d55e98f5cccda` também passou nos três jobs no run `38306907130`. `main` atualizado; VM segue no SHA antigo aguardando operação privilegiada por `su -` do proprietário. |
| 12/10/2026 | Gestão segura de usuários (P1.7) | A rota e a interface de administração foram restauradas para o proprietário; exclusão bloqueia usuários com dados e nunca permite remover o proprietário. CI identificou e corrigiu uma asserção temporal; SHA final `01488a4`, run `38312160754` verde. Conta citada pelo usuário não foi consultada ou excluída. |
| 12/10/2026 | Deploy na VM e migration (P1.2/P1.3/P1.8) | SHA `01488a4` aplicado em `/opt/sophia-test`; migration `0017_financial_idempotency` confirmada. Seis serviços ativos, health live/ready 200 e endpoints sem sessão 401. Houve 502 transitório durante inicialização do frontend, resolvido antes da checagem final. Dump temporário validado antes da migration e removido depois. |
| 12/10/2026 | Cloudflare (P1.7) | Regra ativa por IP, limitada ao host `finance.ruralflow.com.br` e POSTs de setup/login/MFA: 20 requisições em 10 segundos, bloqueio de 10 segundos. Expressão validada; 0 eventos na checagem; não houve teste de bloqueio na produção. |
| 12/10/2026 | SSH e autorização de deploy (P1.8) | O proprietário manteve SSH/22 e senha de `sophia`, com elevação via `su -`, e autorizou deploys quando necessários. A chave root dedicada foi validada; chave privada fora do Git. |
| 12/10/2026 | Documentação de infraestrutura | Corrigido `infra/README.md` para identificar `docker-compose.vm.yml` como perfil de produção e esclarecer que `sophia-test` é um nome operacional histórico, não um ambiente descartável. |

Atualizar esta tabela e as prioridades somente após mudança verificável e checagens correspondentes. Atualizar a documentação operacional junto com cada mudança, incluindo limitações, falhas e comandos de verificação pendentes.
