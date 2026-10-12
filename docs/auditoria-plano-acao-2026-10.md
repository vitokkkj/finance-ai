# Auditoria geral da SophIA — plano de ação

**Data-base:** 12/10/2026
**Escopo:** revisão de UX/UI, domínio financeiro, segurança, testes, GitHub Actions, documentação, integrações e operação. Este documento preserva o estado inicial da auditoria e acompanha as ações; não afirma que uma correção foi aplicada sem evidência verificável.

## Como interpretar as evidências

- **Código local** descreve o checkout revisado. Não prova que esse código esteja publicado na VM.
- **Serviço público observado** descreve respostas HTTP obtidas em 12/10/2026. Health checks e cabeçalhos não provam integridade completa do host ou dos dados.
- **VM:** houve inspeção direta por SSH nesta rodada; estado dos serviços, commit e schema foram registrados abaixo. Cloudflare e Proxmox não foram consultados nesta rodada. A chave do host foi validada, sem ignorar nem contornar a verificação. O caminho de rede anterior à VM segue sem confirmação.
- As linhas citadas são referências do checkout na data da auditoria e podem mudar com alterações posteriores.
- Testes E2E usam somente dados sintéticos. A suíte mockada não substitui o cenário integrado; o cenário integrado usa banco descartável, nunca dados de produção.

## Atualização da execução — 12/10/2026

**Estado do código:** as correções de implementação foram integradas por fast-forward em `main` no SHA `a150afe213fe2910fa9798dfe76e87abf50699dc`; os três jobs passaram na [execução 38306602486](https://github.com/vitokkkj/finance-ai/actions/runs/38306602486). O relatório atualizado foi integrado em `main` no SHA `e45e94922132d896afcddcbfae1d55e98f5cccda`; os três jobs também passaram nesse SHA na [execução 38306907130](https://github.com/vitokkkj/finance-ai/actions/runs/38306907130). A VM ainda serve `542f69e` e a migration `0016_totp_replay`; não houve deploy nem migration no banco de produção. Nenhum dado financeiro foi consultado, alterado ou removido. Os arquivos não rastreados anteriores (`.agents/`, `docs/skills.md` e `sophia_logo_refinada.png`) foram preservados fora do commit.

| P1 | Situação após esta rodada |
|---|---|
| 1.1 — falha da CI | Causa reproduzida e corrigida; os três jobs passaram em `main` no SHA de implementação `a150afe213fe2910fa9798dfe76e87abf50699dc` (run `38306602486`) e no snapshot documental `e45e94922132d896afcddcbfae1d55e98f5cccda` (run `38306907130`). |
| 1.2 — reconciliação financeira | Código e regressões impedem apagar compra quando pagamentos excederiam o total remanescente e bloqueiam edição/exclusão genérica de ocorrência paga. API local e PostgreSQL 17 na CI passaram; deploy na VM permanece pendente. |
| 1.3 — idempotência | Lançamento, transferência, compra e pagamento persistem chave por usuário/operação; retry reproduz o mesmo movimento e reuso com payload distinto retorna `409`. Migration `0017` passou em `alembic upgrade head` e `alembic check` no PostgreSQL 17 da CI; ainda não foi aplicada à VM. |
| 1.4 — PostgreSQL na CI | PostgreSQL 17 descartável, migrations, `alembic check`, suíte API e `pip-audit` passaram no workflow hospedado em `main`, inclusive no snapshot documental `e45e949` (run `38306907130`). |
| 1.5 — E2E | Playwright integrado passou na CI com PostgreSQL 17 no snapshot documental `e45e949` (run `38306907130`): setup, MFA de teste, login, conta/categoria, lançamento, transferência, compra no cartão, pagamento de fatura, retries idempotentes e rota administrativa desativada. Localmente passaram 19/19 testes mockados e 1/1 integrado com API real/SQLite temporário. |
| 1.6 — gate de deploy | O guia exige CI verde no SHA exato e mantém deploy manual; `main` recebeu o SHA validado e o workflow passou no snapshot documental `e45e949`. Não há deploy automático. `main` não tem branch protection nem rulesets; isso permanece no backlog P2. |
| 1.7 — conta/MFA/rate limit | Provisionamento extra foi removido da API e da interface, alinhando o produto a uma conta privada; VM confirmou um usuário e nada foi apagado. Caddy reescreve `X-SophIA-Client-IP` com `CF-Connecting-IP`; a API valida o IP e usa a origem no limitador. Regras do painel Cloudflare não foram inspecionadas. |
| 1.8 — VM | Inspeção direta por SSH concluída; detalhes e limites estão abaixo. A porta 22 permanece aberta por decisão expressa do proprietário. O acesso deve ser feito por senha como `sophia`; para root, o proprietário usa `su -`. |

**VM verificada por SSH:** Debian 13; SHA `542f69e`; seis serviços Compose em execução, web/API/PostgreSQL saudáveis; API e PostgreSQL sem portas publicadas no host; Alembic em `0016_totp_replay`; exatamente um usuário; cerca de 8,7 GB livres em disco de 40 GB e 7,3/8 GB de RAM disponíveis. Não foram lidos `.env`, tokens, e-mails, lançamentos ou saldos. Por escolha do proprietário, TCP/22 permanece aberto no host; SSH permite senha e chave somente para `sophia` (`AllowUsers sophia`), e login direto de `root` está bloqueado (`PermitRootLogin no`). A conta `sophia` e a conta `root` reportaram senha ativa; o servidor anunciou `publickey,password` e a conexão por chave como `sophia` foi confirmada. A senha em si e o comando interativo `su -` não foram testados nem lidos. SSH escuta em todas as interfaces e a política de entrada do nftables é `accept`; isso não comprova exposição pela internet, pois roteador/firewall anterior à VM não foi inspecionado. Cloudflare e Proxmox não foram consultados nesta rodada.

**Falhas e validações pendentes:** o reload de `ssh.service` falhou por causa da ativação por socket; o systemd reiniciou o daemon, o serviço voltou a `active`, `sshd -t` passou e uma nova conexão como `sophia` foi confirmada. O servidor anuncia `publickey,password`, mas não foi feita tentativa interativa para não coletar a senha do proprietário. Uma execução completa inicial de `npm run test:e2e` sem API falhou no cenário integrado por falta do backend local; o teste foi separado por `E2E_INTEGRATED=1`, após isso os 19 mocks passaram e o integrado passou isoladamente. A execução hospedada final passou com PostgreSQL 17. `docker ps` como `sophia` foi negado pelo socket Docker; a conta não tem grupo Docker nem `sudo` instalado. Sem a senha de `root` para `su -`, o deploy e a migration `0017` não foram executados. Docker local continua indisponível; `npm run lint` emite quatro avisos existentes de `!important` na regra de movimento reduzido. O GitHub também emitiu aviso não bloqueante de runtime Node 20 para as actions `checkout` e `setup-node`; acompanhar como P2. `npm audit` e `pip-audit` não encontraram vulnerabilidades. O run anterior #47 no SHA antigo continua falho; a execução nova em `main` é verde.

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

## Prioridade P1 — em andamento; requer evidência de conclusão

Os itens P1 abaixo permanecem **em andamento**, exceto pelo alinhamento de conta única descrito em P1.7, que foi implementado e verificado nesta rodada. O registro dos demais itens não equivale à correção.

### P1.1 Corrigir e tornar verde a validação do SHA implantável

**Evidência:** a execução #47 para `542f69e` falhou no job API. O workflow combina Ruff, checagem de tipos e pytest em uma etapa, então o resumo público não identifica qual deles falhou; `pip-audit` fica condicionado ao sucesso anterior. O mesmo job foi reportado como falho nas execuções #46 e #44.

**Ação:** obter logs autenticados, identificar e corrigir a causa, separar etapas para diagnóstico útil e exigir uma execução verde para o SHA candidato a deploy. Documentar o SHA validado e a relação entre aprovação de CI e deploy manual.

**Resultado:** causa corrigida; API, Frontend e runtime passaram no run [38305965616](https://github.com/vitokkkj/finance-ai/actions/runs/38305965616), SHA `63eee3cb990efe0c87958d13c35effa3ac2cb77b`.

**Referências:** [quality.yml](../.github/workflows/quality.yml#L45), [quality.yml — auditoria Python](../.github/workflows/quality.yml#L52), [deployment.md — deploy manual](deployment.md#L94).

### P1.2 Preservar reconciliação ao editar/excluir compras e ocorrências pagas

**Evidência:** exclusão de transações ligadas a faturas ou recorrências é tratada em `finance_deletion.py`; os totais de fatura limitam saldo em aberto a zero (`max(total - pago, 0)`). A edição genérica impede apenas vínculo a compromisso planejado; não bloqueia de forma equivalente transação gerada por ocorrência de recorrência já paga. Isso pode deixar pagamentos acima das compras da fatura ou valores realizados divergentes da ocorrência original.

**Ação:** impedir exclusão/redução de compras que já tenham pagamentos associados, ou oferecer operações explícitas e auditáveis de estorno/crédito/chargeback; impedir edição de transação de ocorrência paga ou atualizar atomicamente o vínculo e os valores da ocorrência. Definir política de cancelamento versus remoção de histórico e cobrir saldos, pagamentos parciais/totais, recorrência e reconciliação com testes.

**Referências:** [finance_deletion.py](../apps/api/app/finance_deletion.py#L7), [finance_engine.py](../apps/api/app/finance_engine.py#L192), [transactions.py — edição](../apps/api/app/transactions.py#L190), [recurrences.py — baixa](../apps/api/app/recurrences.py#L598), [financial-rules.md](financial-rules.md#L46).

### P1.3 Adicionar idempotência a operações financeiras repetíveis

**Evidência:** os endpoints de criação de transferência, lançamento e pagamento/criação de compra não apresentam chave de idempotência. Repetição após timeout ou retry pode criar mais de um registro; deduplicação por valor/data não é segura, pois movimentos iguais podem ser legítimos.

**Ação:** aceitar chave de idempotência ligada ao usuário autenticado, operação e payload; persistir resultado de forma transacional e definir prazo/retorno para replay. Cobrir timeout/retry concorrente e rejeitar reutilização da chave com payload diferente.

**Referências:** [transfers.py](../apps/api/app/transfers.py#L33), [transactions.py](../apps/api/app/transactions.py#L154), [invoices.py — compra](../apps/api/app/invoices.py#L157), [invoices.py — pagamento](../apps/api/app/invoices.py#L205).

### P1.4 Exercitar PostgreSQL e Alembic na CI

**Evidência:** a configuração CI usa SQLite em memória. A fixture cria tabelas com `Base.metadata.create_all`; não percorre migrations PostgreSQL nem garante comportamento idêntico de chaves estrangeiras, locks ou concorrência.

**Ação:** adicionar serviço PostgreSQL compatível com produção, executar `alembic upgrade head` em banco descartável e a suíte com `TEST_DATABASE_URL`; acrescentar cobertura para isolamento de usuário, constraints, reconciliação e operações concorrentes. Manter SQLite apenas se continuar útil para testes rápidos.

**Resultado:** `alembic upgrade head`, `alembic check`, pytest PostgreSQL e `pip-audit` passaram no job API hospedado do run `38305965616`.

**Referências:** [quality.yml](../.github/workflows/quality.yml#L18), [fixture de testes](../apps/api/tests/conftest.py#L12), [README — execução contra PostgreSQL](../README.md#L124), [README — migrations](../README.md#L131).

### P1.5 Integrar E2E ao CI e acrescentar alguns fluxos integrados

**Evidência/resultado:** antes desta rodada, `test:e2e` não rodava na CI e a suíte usava mocks. O workflow agora inicia API e PostgreSQL descartáveis, aplica migrations e roda Playwright. O cenário integrado passa pelo navegador, proxy Next.js e API, cobrindo setup com MFA fictício de CI, login, conta/categoria, despesa e retry, transferência e retry, compra no cartão e retry, pagamento de fatura e retry; confirma ainda que `/api/admin/users` responde `404`, conforme o produto de conta única. A verificação local integrada inicial passou com SQLite temporário; a tentativa local da suíte completa sem a API falhou somente no cenário integrado, pois a API não estava iniciada. O cenário agora é ativado por `E2E_INTEGRATED=1`, que a CI define.

**Resultado da validação:** o workflow passou nos três jobs no SHA `85815c8a4f2ba29912f5dfdadef0dd4b74dcb2a3`, run `38307311479`; PostgreSQL 17, Alembic e Playwright integrado foram confirmados nesse snapshot. A validação de ownership entre múltiplos usuários foi retirada porque o produto é privado de conta única; os testes de API verificam escopo do usuário autenticado, e o cenário integrado confirma que a rota de administração de usuários está desativada. Dados exclusivamente sintéticos.

**Ação restante:** nenhuma pendência de CI/E2E para este item. A aplicação desta versão na VM está registrada no P1.8. Os cenários integrados usam somente dados sintéticos.

**Referências:** [package.json](../apps/web/package.json#L11), [quality.yml — frontend](../.github/workflows/quality.yml#L57), [spec E2E](../apps/web/e2e/finance-flows.spec.ts), [mocks E2E](../apps/web/e2e/api-mocks.ts).

### P1.6 Definir o gate de deploy e manter documentação operacional sincronizada

**Evidência:** na auditoria inicial, a execução do SHA antigo `542f69e` falhava na API; a causa foi reproduzida e corrigida. Os três jobs passaram no SHA de implementação `a150afe` (run `38306602486`), no SHA documental `e45e949` (run `38306907130`) e no SHA atual do relatório `85815c8` (run `38307311479`). O deploy segue manual, sem workflow de release/deploy automatizado. A documentação Cloudflare contém requisito de rate limit; a revisão anterior relatou ausência de regra no painel, que não foi inspecionado nesta rodada.

**Ação restante:** o gate de CI verde no mesmo SHA, o checklist, a confirmação de versão/health e o procedimento de rollback estão documentados em `deployment.md`. Manter a publicação manual até confirmar migrations, readiness, recuperação e proteção de segredos; deploy/migration na VM aguardam as condições descritas no P1.8. `main` não tem branch protection nem rulesets, registrado no backlog P2.

**Referências:** [deployment.md — checklist](deployment.md#L94), [deployment.md — health e rollback](deployment.md#L92), [deployment.md — rate limit](deployment.md#L32), [quality.yml](../.github/workflows/quality.yml).

### P1.7 Alinhar conta única e concluir rate limiting

**Estado:** política de conta única implementada no código local e documentação; provisioning de usuários adicionais foi removido. A inspeção direta da VM informou exatamente um registro em `users`; o teste automatizado também confirma que as rotas estão desabilitadas e que o usuário inicial permanece intacto. Nenhuma conta nem dado financeiro foi excluído. O limitador local agora recebe IP público por cabeçalho dedicado substituído por Caddy e valida o endereço antes de usá-lo.

**Ação restante:** confirmar no painel Cloudflare os limites de login, bootstrap e MFA como defesa de borda. A origem do limitador da aplicação é passada por `X-SophIA-Client-IP`, substituído por Caddy a partir do `CF-Connecting-IP`; falta confirmar a regra efetiva no painel autenticado.

**Referências:** [main.py — rotas ativas](../apps/api/app/main.py), [teste de provisionamento desabilitado](../apps/api/tests/test_managed_users.py), [deployment.md — política de usuário único](deployment.md#L47), [revisão de segurança — rate limit](revisao-geral-ux-seguranca-2026-10.md#L42), [revisão — ações recomendadas](revisao-geral-ux-seguranca-2026-10.md#L78).

### P1.8 Inspecionar VM e fechar os controles operacionais com acesso direto

**Estado atual:** inspeção por SSH concluída com host key validada e sem ler segredos/dados financeiros. VM Debian 13 no SHA `542f69e`, Alembic `0016_totp_replay`, serviços e recursos registrados acima. Por decisão do proprietário, TCP/22 segue liberado no host e `sophia` é a única conta permitida por SSH; autenticação por senha está habilitada (a chave pública já configurada para `sophia` também continua habilitada). Login SSH direto de `root` está bloqueado. O proprietário acessa `su -` depois de entrar como `sophia`. `sshd -t`, serviço ativo e nova conexão como `sophia` por chave foram verificados; autenticação interativa por senha e elevação com `su -` não foram testadas, pois isso exigiria digitar a senha do proprietário. A camada de rede anterior à VM e sua exposição pública não foram verificadas. Proxmox/backups seguem sem consulta direta nesta rodada.

**Ação restante:** verificar a entrada Cloudflare e a camada de rede anterior à VM, além de obter no Proxmox evidência recente de backup e restauração. A CI do SHA candidato `85815c8` passou; deploy e migration continuam pendentes até confirmar recuperação no Proxmox e executar a etapa privilegiada na sessão do proprietário como `sophia` seguida de `su -`.

**Referências:** [deployment.md — verificação de serviços](deployment.md#L64), [deployment.md — estado Alembic](deployment.md#L69), [revisão — firewall/SSH](revisao-geral-ux-seguranca-2026-10.md#L43), [README de infra](../infra/README.md#L7).

## Prioridade P2 — aberta

| Item | Evidência inicial e recomendação | Referências |
|---|---|---|
| UX móvel, tipografia e densidade | Tabelas usam texto pequeno (há regra de 9 px) e o cabeçalho/filtros podem empurrar conteúdo; cartões exigem rolagem horizontal. Revisar hierarquia, alvos, tabela/cartão responsivo, contraste e primeira dobra em larguras reais sem perder consistência da identidade visual. | [editorial-design.css](../apps/web/src/app/editorial-design.css#L204), [finance-workspace.tsx](../apps/web/src/components/finance-workspace.tsx#L947) |
| Landmarks e seção ativa | Verificar estrutura de `<main>`, link de salto, nome/estado da navegação e foco/teclado. A auditoria identificou landmarks semânticos redundantes e ausência de sinalização suficientemente clara da seção ativa. | [assistant-workspace.tsx](../apps/web/src/components/assistant-workspace.tsx#L1445) |
| URL, voltar/avançar e deep links | Navegação entre áreas mantém a rota `/`; permitir URL direta para seção e sincronizar histórico de navegação, sem quebrar estado de sessão. | [assistant-workspace.tsx](../apps/web/src/components/assistant-workspace.tsx) |
| Recuperação contextual de erros | Falha em uma carga agrupada pode bloquear a tela sem recuperação por recurso. Distinguir erro de estado vazio, oferecer retry localizado e preservar o conteúdo já carregado. | [finance-workspace.tsx](../apps/web/src/components/finance-workspace.tsx#L323) |
| Paginação e custo de consulta | API carrega o histórico sem limite; a paginação do frontend não reduz consulta. Visões de faturas carregam movimentos por fatura e produzem consultas repetidas/N+1. Implementar cursor no servidor e agregação/lote; medir antes de adicionar cache ou infraestrutura. | [transactions.py](../apps/api/app/transactions.py#L106), [finance_views.py](../apps/api/app/finance_views.py#L120), [cards.py](../apps/api/app/cards.py#L43) |
| Política de alteração de fechamento/vencimento | Mudança da configuração do cartão pode aplicar a regra nova a compras futuras sem política de vigência/preview para ciclo. Definir data efetiva, mostrar impacto e cobrir meses curtos e fronteiras. | [cards.py](../apps/api/app/cards.py#L153), [invoices.py](../apps/api/app/invoices.py#L185), [finance_engine.py](../apps/api/app/finance_engine.py#L98) |
| CSP | Cabeçalho observado permite `'unsafe-inline'` em `script-src` e `style-src`. Avaliar nonce/hash compatível com Next.js, primeiro em modo report-only/ambiente controlado, e remover exceção somente após validar hidratação e fluxos. Não há XSS confirmado. | [Caddyfile](../infra/Caddyfile#L13), [revisão anterior](revisao-geral-ux-seguranca-2026-10.md#L44) |
| Semântica de exclusão de recorrência | Resolvido nesta rodada pelo P1.2: edição/exclusão genérica retorna `409` para transação de ocorrência paga; documentação e regressão foram atualizadas. Um fluxo explícito de estorno/cancelamento segue como decisão futura se o produto precisar editar esses registros. | [financial-rules.md](financial-rules.md#L46), [transactions.py](../apps/api/app/transactions.py#L235), [test_recurrences.py](../apps/api/tests/test_recurrences.py#L230) |
| Actions Node 20 | Execuções do GitHub reportaram avisos de actions em Node 20; a revisão anterior apontou atualização necessária para releases compatíveis com Node 24 mantendo pin por SHA. Validar cada action e compatibilidade no runner antes de atualizar. | [quality.yml](../.github/workflows/quality.yml), [guia de actions do GitHub](https://github.blog/changelog/2026-09-23-node-20-is-no-longer-available-in-github-actions/) |
| Backups, recuperação e RPO/RTO | Há declarações documentais diferentes: confirmação de backup/restauração em deployment e pedido de validação no README de infraestrutura. Registrar evidência, escopo, data do último restore drill, RPO/RTO, criptografia e responsável, confirmando no Proxmox diretamente. | [deployment.md](deployment.md#L83), [infra README](../infra/README.md#L7) |
| README de infraestrutura | O guia descreve o Compose de produção da VM com rótulo de ambiente de teste, apesar do serviço real rodar em produção. Corrigir o rótulo e separar instruções de teste local das operações produtivas. | [infra README](../infra/README.md) |
| E-mail proprietário no código | A política de MFA ainda identifica o único proprietário por endereço fixo no código público. Avaliar configuração não secreta de identidade (sem enfraquecer MFA) e reduzir exposição de dado pessoal no repositório. | [auth.py](../apps/api/app/auth.py#L52), [deployment.md](deployment.md#L47) |
| GitHub settings | Consulta autenticada em 12/10/2026 confirmou que `main` não tem branch protection e que o repositório não possui rulesets (`[]`). A documentação exige CI verde no SHA como gate manual, mas isso não impede push direto. Definir proteção que exija `API`, `Frontend` e `Imagens e perfil público` após conferir os nomes no novo run; environments e revisão obrigatória seguem sem avaliação. | [quality.yml](../.github/workflows/quality.yml#L9), [dependabot.yml](../.github/dependabot.yml), [deployment.md — gate manual](deployment.md#L98) |
| Cobertura de navegador e dispositivos | Ampliar além dos mocks para login/MFA, baixa de compromisso, pagamento parcial/total, upload de imagem, tema, gestos e Safari iOS; validar iPhone real (safe area, teclado, PWA e gestos), pois Chromium em 390/820 px não comprova isso. | [revisão anterior](revisao-geral-ux-seguranca-2026-10.md#L46), [revisão — telas reais](revisao-geral-ux-seguranca-2026-10.md#L47) |
| Histórico de recorrências | Lista cobre horizonte móvel materializado de 90 dias; ocorrências fora do horizonte não são pesquisáveis como histórico integral. Definir busca/histórico conforme necessidade de produto, sem materialização ilimitada. | [revisão anterior](revisao-geral-ux-seguranca-2026-10.md#L48), [recurrences.py](../apps/api/app/recurrences.py#L180) |
| Alertas externos | Centro de avisos só funciona com app aberto; push/e-mail não implementados. Decidir depois de confiabilidade: push opt-in iniciado pelo usuário, links diretos e política de privacidade. | [README](../README.md#L183), [revisão anterior](revisao-geral-ux-seguranca-2026-10.md#L45) |

## Prioridade P3 — aberta

| Item | Proposta | Limites e fontes |
|---|---|---|
| Relatórios financeiros | Relatórios mensais por categoria, período e conta, com tendências e navegação até os lançamentos de origem. Todos os agregados devem vir do Finance Engine/PostgreSQL e manter semântica de transferências, pagamentos e reembolsos. | Aplicar depois de reconciliação, PostgreSQL CI e paginação. Padrão de relatórios documentado pelo [YNAB](https://www.ynab.com/blog/ynab-reports-and-data). |
| Metas | Metas opcionais com progresso visível, ligadas a contas/categorias quando houver demanda, sem criar cálculos financeiros no frontend nem tabelas antecipadas sem modelo concreto. | Considerar depois de relatórios e feedback do uso. Exemplo de acompanhamento de metas: [YNAB Goal Tracking](https://www.ynab.com/features/goal-tracking). |
| Importação bancária/OFX e Open Finance | Primeiro melhorar importação manual com arquivo de exemplo, mapeamento de colunas, revisão de duplicidade e desfazer. Decidir OFX antes de ampliar formato. Pluggy exige documentação oficial atual, escopos somente leitura, consentimento/expiração, IDs externos, sincronização idempotente, deduplicação e reconciliação. Nunca armazenar senha bancária. | Não há integração bancária implementada. [integrações.md](integrations.md#L19), [README — capacidades futuras](../README.md#L183). A conciliação com revisão antes de confirmar é um padrão de produto possível, não evidência de requisito já implementado: [Organizze](https://ajuda.organizze.com.br/hc/pt-br/articles/5994220061203-Web-Lan%C3%A7amentos-Concilia%C3%A7%C3%A3o-banc%C3%A1ria). |
| Investimentos, parcelamentos e financiamentos | Documentar domínio futuro e regras necessárias; só implementar na fase apropriada, com valores decimais, calendário e reconciliação. | README registra esses domínios como não implementados: [README](../README.md#L183). |

## Limites que seguem abertos

1. **Deploy na VM:** código em `main`, SHA `a150afe`, com CI verde; atualização da VM e migration `0017` aguardam execução privilegiada. O proprietário definiu acesso como `sophia` e root somente via `su -`; o agente não possui a senha de root e não fará SSH direto como `root`. Para prosseguir, o proprietário precisa iniciar uma sessão privilegiada no terminal de operação ou realizar a etapa manual documentada sem enviar a senha no chat.
2. **Cloudflare/rede anterior:** confirmar limites para autenticação/bootstrap/MFA, configuração do túnel/TLS e exposição do TCP/22; não houve acesso ao painel nem ao roteador/firewall anterior nesta rodada.
3. **Proxmox:** a documentação registra confirmação do proprietário em 12/10/2026 de backup criptografado e restauração testada; falta evidência direta recente de jobs, retenção e teste de restauração no Proxmox.
4. **Branch protection:** decidir e aplicar os checks requeridos em `main`; o estado atual sem proteção foi verificado.
5. **Dados reais:** a revisão visual da interface não reproduz nomes, saldos ou transações do usuário no relatório. Testes permanecem com dados sintéticos.

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

Atualizar esta tabela e as prioridades somente após mudança verificável e checagens correspondentes. Atualizar a documentação operacional junto com cada mudança, incluindo limitações, falhas e comandos de verificação pendentes.
