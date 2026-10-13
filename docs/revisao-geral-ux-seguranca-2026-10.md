# Revisão geral da SophIA — outubro de 2026

## Escopo

Esta revisão cobre a API, regras financeiras, frontend, segurança e operação da SophIA, além dos fluxos de avisos, compromissos, cartões e imagens analisadas pela IA. O painel da zona `ruralflow.com.br` foi conferido diretamente no navegador do Codex em 11/10/2026. O túnel de `finance.ruralflow.com.br` aparece como CNAME com proxy Cloudflare ativado e aponta para `finance-sophia`; o registro não expõe um IP de origem no DNS exibido.

## Prioridades tratadas

### Segurança e backend

- **Limite global de requisições:** a API agora limita corpos `/api/*` a 16 MiB, inclusive quando enviados em blocos sem `Content-Length`; o Caddy também impõe o mesmo teto. O endpoint de imagens preserva limite próprio mais restrito.
- **Replay de TOTP:** um contador TOTP já usado não pode autenticar outra vez. A última janela aceita fica gravada por usuário e é consumida por atualização atômica. A migration `0016_totp_replay` adiciona uma coluna nullable sem alterar lançamentos.
- **Cabeçalhos de proxy:** Uvicorn deixou de confiar em toda a rede privada para `X-Forwarded-*`. A conexão pública continua terminando no Cloudflare e Caddy; o backend não aceita cabeçalhos de proxy de serviços internos como identidade do cliente.
- **Arquivamento de contas:** a API calcula o saldo atual pelo Finance Engine e bloqueia arquivamento quando o saldo é diferente de zero ou não pode ser determinado. O frontend explica o saldo e orienta a zerar ou conciliar a conta.
- **Foto de perfil:** o limite real agora é 48 megapixels, alinhado à interface e à documentação; a imagem é normalizada para 512×512.
- **Previsão e avisos:** a janela de sete dias atravessa a virada do mês; avisos abrem o compromisso, recorrência ou fatura exatos, com destaque e foco. Pagamentos permanecem sujeitos à confirmação do usuário.
- **Visão de faturas:** a página de cartões ganha uma lista consolidada de todas as faturas em aberto, ordenada pelo vencimento mais próximo e com atalho para detalhes/pagamento. Os ciclos selecionados por cartão também ficam em ordem crescente de vencimento; valores são derivados pelo Finance Engine e o endpoint respeita `users.id` da sessão. Faturas futuras só aparecem quando já há saldo ou compras registradas para o ciclo.
- **Navegação de dados:** listas extensas usam páginas de 15 itens, inclusive faturas e compras/pagamentos de ciclos, cartões, lançamentos, ocorrências, compromissos, regras, conversas, avisos e listas de Preferências. O controle confere com a lista filtrada e o foco em item vindo de aviso respeita sua página. A navegação geral de ocorrências fica paginada, sem o antigo controle “Mostrar histórico”.
- **Consulta por categoria:** abrir o nome ou a ação “Ver lançamentos” em uma categoria leva aos movimentos daquela categoria com o filtro aplicado.
- **Contas de acesso:** correção após esclarecimento do proprietário em 12/10/2026: contas de login gerenciadas permanecem disponíveis, com criação/exclusão restrita ao proprietário e sem cadastro público. A implementação foi validada e publicada na VM. A API recusa excluir o próprio proprietário ou qualquer conta com registros pessoais/financeiros associados; nenhum registro de produção foi consultado ou removido.
- **Cartões e ciclo futuro:** a regra de saldo inicial importado de fatura futura está documentada: compras/parcelas assumidas reduzem o limite disponível; intenção de compra ainda não realizada não deve ser lançada como fatura.

### Frontend e uso móvel

- O menu móvel usa o mesmo breakpoint responsivo, pode abrir por gesto iniciado na borda esquerda e fechar com gesto, backdrop ou `Escape`.
- O drawer tem isolamento do conteúdo de fundo, foco inicial e restauração de foco, atributos ARIA e bloqueio de rolagem do documento enquanto está aberto.
- A navegação lateral permanece rolável em telas baixas; áreas de toque do controle foram ampliadas.
- O drawer de navegação usa o breakpoint móvel próprio; o painel de contexto financeiro inicia fechado em toda a faixa responsiva até 1120 px, alinhado ao overlay CSS.
- A lateral reserva uma faixa fixa para a conta e a saída, e usa o espaço restante para mostrar e rolar várias conversas; em telas baixas, a própria lateral também pode rolar sem esconder esses controles. “Nova conversa” ficou compacta. No celular, “Atualizar aplicativo” recarrega os dados do app e restaura a conversa ou seção aberta; aparece um aviso antes de descartar rascunho e o botão fica desativado durante uma resposta.
- No celular, Enter quebra linha e o botão de envio envia a mensagem; no computador, Enter continua enviando e Shift+Enter quebra linha. Campos de texto, datas e listas usam fonte mínima de 16 px para evitar o zoom automático do Safari ao focá-los, mantendo o zoom por gesto disponível.
- O seletor do resumo foi exercitado no navegador: ao escolher outro mês, fluxo e categorias são atualizados; o rótulo agora informa “Mês analisado”. A previsão “A pagar” continua mostrando o mês corrente, conforme sua função de compromissos próximos.
- Categorias exibem **Receitas** antes de **Despesas**.
- O tratamento de imagens do chat aceita até quatro anexos e encaminha o tipo WebP verdadeiro depois da normalização.
- Em celulares e tablets, o contexto financeiro inicia fechado; o contador de avisos fica ao lado do sino sem sobreposição; e o resumo mensal usa linhas de rótulo/valor para evitar colisões em larguras estreitas. Os três comportamentos têm cobertura automatizada em 390 px e 820 px.
- **Portabilidade e importação:** a tela Minha conta permite exportar os dados financeiros em JSON; Lançamentos aceita um CSV com layout documentado e mostra a prévia, correspondências possíveis e ações por linha antes de exigir confirmação. O primeiro formato importa somente receitas e despesas de conta; não grava a prévia.

## Riscos e melhorias que permanecem

| Prioridade | Item | Estado e próxima ação |
|---|---|---|
| P0 dados | Backup e recuperação | Proprietário confirmou em 12/10/2026 que os backups do Proxmox são criptografados e a restauração foi testada; registrado como validado com base nessa confirmação operacional. A exportação autoatendida em JSON foi implementada. Desfazer/recuperar exclusões continua como evolução possível. |
| P1 concluído | Rate limit no Cloudflare | Em 12/10/2026 foi ativada a regra **Autenticacao - limite por IP**, restrita ao host financeiro e aos POSTs de setup, login e pareamento MFA: 20 requisições por IP em 10 segundos, com bloqueio por 10 segundos. O painel mostrou a regra ativa e sem eventos no momento da conferência. A regra não altera os demais domínios da zona. |
| P1 concluído; P2 rede upstream | SSH e firewall da VM | Atualização em 12/10/2026: TCP/22 permanece aberto; `sophia` continua com senha e chave. `root` aceita chave pública, com `PermitRootLogin prohibit-password` e `AllowUsers sophia root`; a chave dedicada foi instalada e o login root foi confirmado. O proprietário pode continuar usando `su -`. O serviço está ativo e a política efetiva foi conferida. A cadeia `input` do nftables segue `accept`; o caminho de rede anterior à VM permanece sem verificação. |
| P1 em andamento | MFA por conta gerenciada | Código e migrations passaram em CI PostgreSQL 17 `38326869097`: MFA TOTP obrigatório por conta, segredos cifrados com Fernet, pareamento limitado e com expiração de dez minutos, anti-replay e reset do proprietário com senha+TOTP e revogação das sessões da conta. A listagem administrativa informa o estado sem expor o segredo. Merge, migration na VM e provisionamento/backup independente da chave Fernet ainda pendentes. |
| P2 segurança/operação | Ciclo de vida da chave MFA | `MFA_ENCRYPTION_KEY` não é recuperável pelo banco. Fazer backup separado e testar restauração; rotação exige re-cifrar segredos antes de trocar a chave. Perda requer re-parear as contas gerenciadas após reset pelo proprietário. |
| P2 segurança | CSP com `unsafe-inline` | Permanece para compatibilidade com Next.js. Avaliar nonce/hash em ambiente de produção e remover a exceção apenas após validar hidratação, fontes e navegação. Não há XSS confirmado nesta revisão. |
| P2 produto | Notificações do sistema | Os avisos são internos enquanto o site está aberto. Push no iPhone requer service worker, inscrição iniciada por ação explícita e configuração de push; manter opt-in e links diretos para o item. |
| P2 qualidade | Automação do navegador | CI `38326869097` passou fluxo integrado com dados sintéticos (pareamento de conta gerenciada, login posterior, reset pelo proprietário e exclusão) e suíte mockada. A expiração segue coberta pela API. A suíte mockada cobre período/previsões, resposta financeira do chat, exportação, importação CSV, faturas, resumo e avisos em larguras móveis. Lacunas: baixa de compromissos, pagamento parcial/total, upload de imagens, tema, gestos e Safari/iOS real. |
| P2 UX | Verificação visual em telas reais | Larguras de 390 px e 820 px passaram em Chromium com API sintética; isso verifica layout e interações básicas, não reproduz teclado, safe area, PWA, gestos ou Safari do iPhone real. A checagem física no iPhone continua pendente. |
| P2 operação | Histórico de ocorrências fora do horizonte | A lista paginada contém as ocorrências materializadas no horizonte móvel de 90 dias. O aviso abre o registro exato; ocorrências fora desse horizonte não são materializadas nem pesquisáveis como histórico completo. |
| P2 concluído | Governança de `main` | Em 12/10/2026, ruleset `24959980` foi ativado após decisão do proprietário: PR obrigatório, checks `API`, `Frontend` e `Imagens e perfil público` estritos, sem aprovação humana, bypass, exclusão ou force-push. Os três contextos passaram no PR #6 em `38326869097`. |
| P2 operação | Revisar limite de borda após uso | A regra Cloudflare está ativa e cobre apenas rotas de autenticação no host financeiro. Acompanhar eventos e relatos de bloqueio legítimo; ajustar o teto se o uso real mostrar falso positivo, mantendo o limitador por conta/IP da API. O painel Free mostrava `1/1` regras de rate limit ocupadas em 12/10/2026. |
| P2 operação | Evidência direta de rede e Proxmox | A configuração do host, Compose, SSH e aplicação foi inspecionada na VM. Não foi verificado o firewall/roteador anterior à VM nem coletada evidência direta de jobs, retenção e restore drill no Proxmox. O proprietário confirmou backup criptografado e restauração testada em 12/10/2026; um dump temporário pré-deploy também foi validado e removido após a publicação. |

Pontos fortes confirmados no código: não há cadastro público; o bootstrap inicial é protegido por token; somente o proprietário administra contas de login; senhas usam Argon2; sessões persistem apenas hashes aleatórios; cookie de sessão é `HttpOnly`, `Secure` e `SameSite=Strict`; operações financeiras usam a sessão autenticada e filtram por `users.id`; PostgreSQL não publica porta; imagens do chat não são persistidas no histórico. MFA individual e migrations passaram no CI `38326869097`; o merge e deploy ainda estão pendentes. A chave Fernet fica fora do banco e precisa de backup independente. A regra de borda do Cloudflare está ativa; o caminho de rede anterior à VM permanece sem verificação direta.

## Avisos de vencimento

Atualmente, os avisos atualizam ao abrir o app, ao voltar para a aba e periodicamente enquanto ele está aberto. Eles apontam para o registro que exige atenção e permitem marcar como pago/recebido depois da conferência. Ainda não há alerta do sistema, e-mail ou push com o app fechado.

As referências consultadas mostram padrões úteis: [Organizze — alertas de contas vencendo ou atrasadas](https://ajuda.organizze.com.br/hc/pt-br/articles/360035805714-Android-Vis%C3%A3o-geral-Alertas) leva às contas que podem ser baixadas; [Mobills — personalizar a tela inicial](https://mobills.zendesk.com/hc/pt-br/articles/360051434294-Como-personalizar-a-tela-inicial-do-meu-Mobills) apresenta pendências e alertas. Para push em iOS, a [documentação do WebKit](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/) exige um web app na Tela de Início, permissão iniciada pelo usuário e assinatura push.

## Verificações e evidências

| Verificação | Resultado |
|---|---|
| API — CI PostgreSQL 17 | **Histórico:** 193 passaram; 2 avisos não bloqueantes no [workflow 38312160754](https://github.com/vitokkkj/finance-ai/actions/runs/38312160754), associado à publicação anterior. A validação posterior do SHA implantado `41368d93bd96c4e1814890d29110323fbec5e864` passou no workflow `38317703475`; localmente, a auditoria registrou 196 testes aprovados e 3 ignorados por limitações de plataforma/concorrência. |
| API — execução local no Windows | **Histórico:** 191 passaram; 2 foram ignorados por dependerem de permissões POSIX indisponíveis no Windows. A contagem posterior registrada para o SHA implantado é 196 aprovados e 3 ignorados. |
| Ruff | Passou. |
| Mypy | Passou em 33 arquivos da API. |
| Biome lint | Passou com quatro avisos existentes sobre `!important` na regra `prefers-reduced-motion`. |
| TypeScript | Passou. |
| Build Next.js | Passou; rotas estáticas geradas. |
| Playwright E2E | Suíte mockada local: 22 passaram. O CI `38326869097` passou o fluxo integrado com PostgreSQL descartável, incluindo MFA individual (pareamento, login e reset pelo proprietário). Os **20 testes** do CI em Chromium abaixo pertencem à execução histórica anterior; nenhum dado real foi usado. Permanecem lacunas de fluxos UI e Safari/iOS descritas em “Riscos e melhorias que permanecem”. |
| Publicação anterior (histórico) | Em 12/10/2026, a VM foi atualizada para `01488a4c161fedac7444d1885b2b0b177a2bd546`; seis serviços estavam ativos, API/web/PostgreSQL saudáveis, migration `0017_financial_idempotency` aplicada e health checks públicos retornavam 200. Esse estado foi substituído pelo deploy posterior abaixo. |
| Caddyfile 2.11.6 | Configuração validada no ambiente da VM. |
| Compose da VM | Configuração validada sem imprimir valores interpolados. |
| Deploy e migration | **Estado atual registrado:** commit `41368d93bd96c4e1814890d29110323fbec5e864` publicado após CI verde no [workflow 38317703475](https://github.com/vitokkkj/finance-ai/actions/runs/38317703475); Alembic `0018_idempotency_tombstones (head)`. Seis serviços ativos; API/web/PostgreSQL saudáveis; PostgreSQL não publica porta no host. O commit `01488a4c161fedac7444d1885b2b0b177a2bd546` e a migration `0017_financial_idempotency` são o deploy anterior, mantido acima apenas como histórico. |
| HTTP público | `/api/health/live` e `/api/health/ready` retornam 200; `/api/accounts` e `/api/admin/users` sem sessão retornam 401; `/api/docs` retorna 404. HSTS, CSP, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, Referrer-Policy e Permissions-Policy foram observados na revisão anterior; não foram reamostrados neste deploy. |
| Painel Cloudflare | Regra de rate limit ativa e limitada ao host financeiro e rotas de autenticação; painel validou a expressão. O estado atual de Full TLS, Browser Integrity Check, Bot Fight Mode, Under Attack e DNS permanece conforme a inspeção de 11/10/2026, não foi novamente alterado. |

## Próximos passos

1. Acompanhar eventos e possíveis falsos positivos da regra de rate limit ativa após uso real.
2. Fazer a verificação final no iPhone: teclado, safe areas, PWA, rolagem/gestos e interação do menu/contexto.
3. Refinar o importador após uso de arquivos de exemplo; decidir sobre OFX, mapeamento de colunas, imagens revisáveis e desfazer antes de ampliar o escopo.
4. Planejar push opt-in depois de validar o fluxo no iPhone, sem colocar conversas financeiras em cache.
