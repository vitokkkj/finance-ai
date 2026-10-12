# Implantação e operação

## Topologia pública

A VM publica a aplicação por um túnel de saída da Cloudflare. `cloudflared`, Caddy e Next.js compartilham a rede Docker `edge`; o túnel encaminha `finance.ruralflow.com.br` para `http://caddy:80`. O TLS público termina na Cloudflare. Caddy recebe HTTP apenas dentro da rede privada do Compose, define cabeçalhos de segurança e encaminha para o frontend. Nenhum serviço publica porta no host.

Na zona Cloudflare, mantenha ativa a regra de redirecionamento 301 `http://finance.ruralflow.com.br/*` → `https://finance.ruralflow.com.br/${1}`, preservando a query string. Ela vale somente para SophIA. Não habilite a opção global “Always Use HTTPS” da zona se isso também alterar o site principal ou outros subdomínios.

Next.js encaminha `/api/*` para FastAPI. API e worker acessam PostgreSQL pela rede `data`, marcada como interna; a API também participa da rede `app`. O worker e o banco não têm interface na rede pública. O túnel não alcança diretamente a API nem o banco.

Na implantação, Next.js recebe `API_INTERNAL_URL=http://api:8000` durante o build para que o proxy de `/api/*` alcance a API pela rede Docker. API, web, worker, Caddy e `cloudflared` usam sistema de arquivos raiz somente leitura e `/tmp` temporário. O worker não recebe o segredo TOTP do proprietário. A API recebe conexões apenas do serviço web; para limitar por IP público, usa um cabeçalho dedicado que Caddy reescreve com o endereço fornecido pela Cloudflare, além da chave por conta.

## Acesso administrativo SSH

A porta SSH 22 permanece acessível nas interfaces da VM, conforme decisão do proprietário em 12/10/2026. A regra `input` do nftables não restringe essa porta; o firewall de rede/roteador anterior à VM não foi inspecionado, então esta documentação não afirma que a porta esteja acessível pela internet. `sophia` continua aceitando senha (`PasswordAuthentication yes`) e chave pública; o proprietário pode entrar por senha e executar `su -` para obter root. Login direto de `root` aceita somente chave pública (`PermitRootLogin prohibit-password`), com `AllowUsers sophia root`; senha para root via SSH permanece desativada. Em 12/10/2026, uma chave Ed25519 dedicada foi instalada em `/root/.ssh/authorized_keys`; a chave e sua impressão digital ficam fora deste repositório público. A senha privada da VM não foi solicitada nem armazenada. O serviço `ssh` foi iniciado depois de criar `/run/sshd`; a configuração efetiva foi validada e uma conexão como `root` com a chave dedicada confirmou `uid=0`. Não altere a política de acesso à porta 22 sem alinhar com o proprietário.

A API roda com um único worker para manter o limitador de tentativas de login consistente. Caddy substitui `X-SophIA-Client-IP` pelo `CF-Connecting-IP` recebido na origem Cloudflare; Next.js encaminha esse cabeçalho à API, que valida o endereço IP antes de usá-lo junto com a conta no limitador. A API não deve ser publicada diretamente nem aceitar esse cabeçalho de origens não confiáveis. A validação de senha e a etapa de MFA compartilham o mesmo orçamento de tentativas por conta e origem. Bloqueios ativos não são expulsos por novas origens: se a tabela de chaves atingir a capacidade configurada, novas chaves recebem 429 até que entradas expirem. Esta instalação foi projetada para uma instância de API; não escale réplicas sem antes mover o limitador para um mecanismo compartilhado.

Fotos de perfil aceitam JPEG, PNG ou WebP até 25 MB e 48 megapixels no navegador e na API. O navegador corrige a orientação e reduz a foto a no máximo 512 px antes do envio; a API valida novamente e armazena WebP associado ao usuário. A leitura exige uma sessão autenticada e envia Cache-Control: no-store; a migration 0013_profile_avatar só acrescenta os campos opcionais do perfil.

Fotos do chat podem ser selecionadas ou coladas da área de transferência; cada arquivo original pode ter até 25 MB e 48 megapixels antes da redução no navegador. Cada mensagem aceita até quatro imagens preparadas, com até 3 MB de dados por imagem. O cliente tenta reencodar cada imagem em WebP com até 2.048 px e também pode enviar PNG ou JPEG quando o navegador não oferece exportação WebP no canvas. Caddy e API limitam corpos HTTP a 16 MiB; a rota do chat mantém o limite específico de 12,5 MB. A API valida formato e resolução de até 4 megapixels por imagem, remove metadados e normaliza tudo em WebP antes de encaminhar somente ao provider ChatGPT conectado no turno atual. O conteúdo da imagem não é persistido no histórico financeiro. A API bloqueia anexos quando AI_PROVIDER=ollama.

A API limita mensagens do chat a 20 por usuário a cada 60 segundos e mantém até três respostas simultâneas por processo. Os limites são locais à instância única descrita acima e reiniciam com o processo. Desde 12/10/2026, a zona Cloudflare tem uma regra ativa de borda para autenticação e bootstrap, descrita abaixo; revise-a se as rotas ou o fluxo de login mudarem.

O repositório público está em [vitokkkj/finance-ai](https://github.com/vitokkkj/finance-ai), sob licença MIT. Endereços privados da VM, arquivos `.env`, tokens de túnel, credenciais OAuth e dados financeiros não pertencem ao GitHub.

## Requisitos

- Docker Compose V2 `2.24.4` ou superior, por causa de `!reset` e `!override` usados para remover portas e mounts de desenvolvimento.
- Zona `ruralflow.com.br` gerenciada pela Cloudflare e um túnel dedicado chamado `finance-sophia`. Não reutilize um túnel que publique outros domínios.
- Conectividade de saída da VM para a Cloudflare na porta `7844` (UDP ou TCP). O acesso da aplicação não exige portas de entrada, pois usa o túnel de saída; o SSH administrativo na porta 22 permanece ativo conforme a política documentada acima.
- Token do túnel salvo em arquivo local privado no servidor. `cloudflared` executa como usuário não-root e lê `/run/secrets/cloudflare_tunnel_token`; o token não é colocado na linha de comando, no `.env` nem no Git.
- Segredo TOTP do proprietário em `OWNER_TOTP_SECRET`, no `.env` privado da VM. Gere-o em um terminal confiável com `python3 scripts/generate-owner-totp.py` e mantenha a chave fora do banco e do repositório. O QR de pareamento do Authy é exibido pela aplicação após a autenticação da senha e autorização temporária do servidor.
- Chave Fernet em `MFA_ENCRYPTION_KEY`, obrigatória para a API em produção. Gere uma única chave em terminal confiável com `python3 -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'`; grave-a no `.env` privado com modo `0600` e mantenha uma cópia independente em um gerenciador de segredos ou backup offline protegido. Não gere outra chave a cada deploy: ela é necessária para descriptografar os autenticadores das contas gerenciadas.
- `MFA_ENROLLMENT_TOKEN` autoriza somente o primeiro pareamento do autenticador do proprietário. Gere com `openssl rand -hex 32`, use-o uma vez na tela privada do proprietário e remova a variável do `.env` após confirmar o código. Contas gerenciadas não usam esse token; cada pessoa inicia o pareamento com seu próprio e-mail e senha.
- Token aleatório e temporário para criar a primeira conta. Gere com `openssl rand -hex 32` e configure em `INITIAL_SETUP_TOKEN` somente durante o bootstrap.
- O limitador combina endereço de origem e conta, mas fica em memória e reinicia junto com a API. A regra de borda da Cloudflare cobre os POSTs de login, bootstrap e pareamento MFA. Não substitua o limitador da API por essa regra: ela agrega requisições por IP e existe como defesa adicional.
- `POSTGRES_PASSWORD` aleatória, com letras e números para evitar codificação especial na URL do banco.

Não reutilize valores de desenvolvimento do `.env.example` em produção. Não cole tokens, senhas, códigos TOTP, cookies ou credenciais OAuth no chat, em issues, logs ou workflows.

## Rota Cloudflare

No túnel dedicado `finance-sophia`, a rota publicada deve usar:

- Hostname público: `finance.ruralflow.com.br`
- Serviço interno: `http://caddy:80`
- Catch-all: `http_status:404`

Ao salvar a rota, a Cloudflare cria o DNS CNAME proxied apontando para o túnel. O conector `cloudflared` precisa estar na rede Docker `edge` deste Compose para resolver `caddy`. Não crie registros A/AAAA apontando para o IP da VM e não publique as portas 80/443 do host.

O hostname público permite que qualquer visitante alcance a tela de login. Não há cadastro público. O bootstrap controlado cria a conta inicial do proprietário; depois de configurada, `requires_setup` deve permanecer `false`. O proprietário autenticado pode listar, criar e excluir contas de login em Preferências pela rota `/api/admin/users`. Todas as contas exigem senha e TOTP; cada conta gerenciada tem segredo próprio cifrado com Fernet usando `MFA_ENCRYPTION_KEY`. Uma conta gerenciada recém-criada permanece sem pareamento e não pode entrar até concluir setup e confirmação do MFA, que exigem sua senha e expiram em dez minutos. O proprietário exige sua senha, TOTP e o token temporário apenas para seu próprio pareamento inicial. A exclusão de outra conta é recusada com `409` se houver qualquer dado pessoal ou financeiro associado, e encerra suas sessões quando permitida. A rota pública não substitui a autenticação da aplicação.

## Preparar a VM e publicar

1. No `.env` privado da VM, defina `APP_DOMAIN=finance.ruralflow.com.br`, `OWNER_TOTP_SECRET`, `MFA_ENCRYPTION_KEY`, credenciais PostgreSQL e `CLOUDFLARE_TUNNEL_TOKEN_FILE=./secrets/cloudflare-tunnel-token`. Armazene uma cópia protegida da chave Fernet fora da VM e fora do banco. Configure `INITIAL_SETUP_TOKEN` somente se ainda não houver uma conta; remova-o depois do bootstrap. Para o primeiro pareamento do autenticador do proprietário, configure temporariamente `MFA_ENROLLMENT_TOKEN` com um valor aleatório de pelo menos 32 caracteres.
2. Crie o diretório `secrets` como `root` com permissão `0700` e o arquivo `cloudflare-tunnel-token` como `root:root`, permissão `0644`. A pasta não é rastreada pelo Git e impede leitura por usuários locais sem privilégio; o arquivo precisa ser legível pelo processo não-root do container `cloudflared`.
3. Crie o túnel dedicado `finance-sophia` no painel Cloudflare e instale o token desse conector diretamente no arquivo secreto da VM por um canal administrativo confiável; não o envie pelo chat nem o grave em histórico de shell. Não publique a rota ainda. Não reutilize o túnel `ruralflow-vm`, que já publica `ruralflow.com.br` para outro serviço.
4. Valide a configuração sem imprimir valores interpolados: `docker compose -f docker-compose.yml -f docker-compose.vm.yml config -q`.
5. Inicie os serviços: `docker compose -f docker-compose.yml -f docker-compose.vm.yml up -d --build`. Confirme que os seis serviços estão em execução e que o Compose não publica portas no host.
6. Só depois da validação interna, publique no túnel dedicado a rota `finance.ruralflow.com.br` → `http://caddy:80`, com fallback `http_status:404`.
7. Confirme que o conector `cloudflared` está conectado no painel e acesse `https://finance.ruralflow.com.br`. Verifique os cabeçalhos HSTS, proteção contra framing, MIME sniffing e permissões do navegador. Cookies usam o prefixo `__Host-`, `Secure`, `HttpOnly`, `SameSite=Strict` e validade máxima de 24 horas. A conta existente exige novo login com senha e TOTP; a migration `0011_public_auth_hardening` invalida sessões antigas, mas preserva os dados financeiros.
8. No primeiro login do proprietário, informe e-mail e senha; a aplicação então solicita o MFA. Para parear o Authy, escolha **Configurar autenticador**, informe o token temporário, escaneie o QR e confirme o código atual do Authy. O QR vale por dez minutos. Depois da confirmação, remova `MFA_ENROLLMENT_TOKEN` do `.env` e recrie a API; o acesso do proprietário continuará exigindo senha e TOTP. O proprietário pode criar contas de login gerenciadas em Preferências; cada pessoa deve autenticar com sua senha, gerar seu próprio QR TOTP e confirmar o código em até dez minutos antes do primeiro login. Não habilite cadastro público.

A migration `0011_public_auth_hardening` revoga sessões antigas para exigir novo login. A migration `0012_owner_mfa_enrollment` adiciona apenas o estado e o prazo temporário de pareamento. A migration `0016_totp_replay` acrescenta o contador de códigos já consumidos e impede que o mesmo código abra sessões ou autorize novamente uma ação sensível. A migration `0017_financial_idempotency` introduziu os campos de idempotência nos movimentos. A migration `0018_idempotency_tombstones` cria uma tabela separada, preserva as chaves existentes e mantém a garantia de não duplicar uma operação depois da exclusão explícita do movimento; não remove nem altera lançamentos financeiros. As migrations `0017` e `0018` estão aplicadas na VM; `0018_idempotency_tombstones` é o head atual. O downgrade de `0018` é bloqueado; uma reversão exige restaurar um backup validado, não apagar a tabela manualmente. A compatibilidade de leitura/gravação com as colunas de `0017` cobre retries feitos durante um rollback de imagem, enquanto o movimento original ainda existir. Não mantenha uma versão anterior atendendo exclusões financeiras depois de `0018`: ela não preserva tombstones ao apagar a linha; nesse cenário, restaure também o banco do backup junto com a imagem anterior.

No checkout local desta rodada, a migration `0019_managed_user_totp` adiciona o campo nullable do segredo TOTP cifrado; ela não altera dados financeiros e seu downgrade é bloqueado para evitar apagar autenticadores. A migration `0020_transaction_cursor_index` adiciona o índice da paginação. A cadeia local foi conferida como `0018 → 0019 → 0020`; `0019` e `0020` ainda não estão aplicadas na VM nem validadas em CI. Não trate este estado local como deploy.

O banco guarda apenas o segredo TOTP individual cifrado, mas não contém a chave `MFA_ENCRYPTION_KEY`; backups PostgreSQL sem essa chave não conseguem restaurar o MFA das contas gerenciadas. Faça backup da chave em local independente e teste a recuperação. A aplicação ainda não automatiza rotação: antes de trocar a chave, re-cifre cada segredo com a chave nova em uma migração controlada, verifique que todos podem ser descriptografados e mantenha o backup antigo até validar o login. Substituir a chave sem re-cifrar torna os segredos atuais ilegíveis. Se a chave for perdida, gere uma nova, configure-a antes de iniciar a API e use, para cada conta gerenciada, `POST /api/admin/users/{id}/mfa/reset`; essa operação exige uma sessão do proprietário e sua senha e TOTP, revoga todas as sessões da pessoa e limpa apenas seu MFA, preservando os dados financeiros para novo pareamento. A chave e o MFA do proprietário são separados e não são redefinidos por essa rota.

### Publicação anterior confirmada em 12/10/2026

A VM foi atualizada manualmente para o commit `01488a4c161fedac7444d1885b2b0b177a2bd546`, depois de CI verde no [workflow 38312160754](https://github.com/vitokkkj/finance-ai/actions/runs/38312160754). O Alembic reporta `0017_financial_idempotency (head)`. Os seis serviços do Compose estão ativos; API, PostgreSQL e web estão saudáveis. Os endpoints públicos `/api/health/live` e `/api/health/ready` retornaram `200`; `/api/accounts` e `/api/admin/users`, sem sessão, retornaram `401`; `/api/docs` retornou `404`. Durante a recriação dos containers, o Caddy respondeu `502` enquanto o serviço web iniciava; depois que o Next.js ficou pronto, os health checks públicos foram repetidos e passaram.

Antes da migration foi criado um dump PostgreSQL temporário com permissão `0600`; o cabeçalho e a listagem de restauração foram validados sem ler registros. Após a aplicação e os health checks, esse arquivo temporário foi removido e a ausência confirmada. A retenção de backup continua no Proxmox, fora do repositório.

### Atualização de idempotência confirmada em 12/10/2026

Com autorização do proprietário, a VM em `/opt/sophia-test` foi atualizada para o SHA `41368d93bd96c4e1814890d29110323fbec5e864`, depois de todos os jobs do [workflow 38317703475](https://github.com/vitokkkj/finance-ai/actions/runs/38317703475) passarem. A CI validou lint e tipos, migrations e testes PostgreSQL, E2E Playwright, auditorias de dependências, Compose e builds de produção. O `docker compose ... up -d --build --wait` concluiu; seis serviços estão ativos, com API, web e PostgreSQL saudáveis. O Alembic reporta `0018_idempotency_tombstones (head)`.

Pelo hostname HTTPS, `/api/health/live` e `/api/health/ready` responderam `200`; `/api/accounts` e `/api/admin/users`, sem sessão, responderam `401`; `/api/docs` respondeu `404`. A resposta de readiness incluiu HSTS, CSP, `X-Content-Type-Options`, `X-Frame-Options`, Referrer-Policy e Permissions-Policy. Inspeção de `NetworkSettings.Ports` confirmou que API, web, PostgreSQL e Caddy não publicam portas no host. O SSH permaneceu ativo; `sshd -T` confirmou `PasswordAuthentication yes`, `PermitRootLogin without-password`, `PubkeyAuthentication yes`, `KbdInteractiveAuthentication no` e `AllowUsers sophia`/`root`.

Antes da migration foi criado um dump custom PostgreSQL temporário de 143.674 bytes, modo `0600`, sem criptografia. `pg_restore --list` passou dentro do container PostgreSQL; o arquivo foi removido após as checagens e sua ausência confirmada. A máquina tinha 8,7 GB livres de 40 GB e 7,3 GiB de memória disponível após o deploy. Não foram lidos registros financeiros, `.env` ou segredos. O host não tinha `pg_restore` instalado, então a listagem foi validada pela ferramenta do container.

Na zona `ruralflow.com.br`, a regra ativa **Autenticacao - limite por IP** corresponde ao host `finance.ruralflow.com.br`, método `POST` e às rotas `/api/auth/setup`, `/api/auth/login/check`, `/api/auth/login`, `/api/auth/mfa/enrollment/start` e `/api/auth/mfa/enrollment/confirm`. Ela conta por IP e bloqueia por 10 segundos depois de mais de 20 requisições em 10 segundos. A regra foi validada pelo Cloudflare e aparece ativa; não foi gerado tráfego de força bruta para testá-la em produção. Na inspeção de 12/10/2026, o plano Free mostrava `1/1` regras de rate limit em uso; consolide futuras rotas nesta regra ou revise o plano antes de adicionar outra.

## Verificação de segurança pós-deploy

- `docker compose -f docker-compose.yml -f docker-compose.vm.yml ps`: confira que web, API, worker, PostgreSQL, Caddy e cloudflared estão ativos.
- Verifique que o Compose de produção não publica portas no host: `docker compose -f docker-compose.yml -f docker-compose.vm.yml port web 3000`, `port api 8000`, `port postgres 5432` e `port caddy 80` não devem retornar um endereço público.
- Acesse `/api/health/live` e `/api/health/ready` pelo hostname HTTPS; confirme redirecionamento HTTP→HTTPS e os cabeçalhos `Strict-Transport-Security`, `Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` e `Permissions-Policy`.
- Uma chamada sem sessão a `/api/accounts` e às rotas `/api/admin/users` deve retornar `401`; com sessão não proprietária, as rotas administrativas devem retornar `403`. Em ambiente de teste isolado, confirme que a sessão do proprietário pode listar/criar e excluir um usuário sintético sem dados; uma conta com dados deve retornar `409` sem apagar registros. `/api/docs` deve retornar `404` em produção. Com o proprietário já criado, `requires_setup` em `/api/auth/setup-state` deve ser `false`.
- Confirme que a rota de bootstrap está indisponível depois que a conta do proprietário existir e que um login inválido não cria sessão.
- Confira `alembic current`, integridade dos saldos no Finance Engine e logs sem segredos. Os backups e a recuperação permanecem sob responsabilidade do Proxmox, fora deste repositório.

Não teste login de pessoas reais nem crie usuários adicionais na produção. Use contas e dados sintéticos somente em ambiente descartável; nunca faça exclusões experimentais no banco de produção.

## Desenvolvimento local

O arquivo `.env.example` e `docker compose up` são para desenvolvimento em `http://localhost:3000`. O frontend fica ligado a `127.0.0.1`; o cookie `Secure` é desligado para HTTP local e o TOTP pode ficar sem configuração. API e PostgreSQL continuam sem portas publicadas. Não use esse modo para exposição pública.

A suíte E2E mockada roda com `npm run test:e2e`. O cenário integrado é habilitado no CI com `E2E_INTEGRATED=1`, API isolada, PostgreSQL descartável e uma chave TOTP fictícia exclusiva para automação; nunca reutilize essa chave fora do CI.

## Integração com o plano ChatGPT

O OAuth para a VM é concluído no computador que tem o navegador. Depois, as credenciais protegidas são transferidas por SSH e a VM renova os tokens. O host da VM precisa manter seu identificador estável. Consulte o fluxo oficial de [Sign in with ChatGPT para VMs auto-hospedadas](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms). Tokens ficam em volume privado montado somente na API, com permissões restritas. Não configure fallback para chamadas pagas de API.

## Dados e recuperação

Os backups da VM são gerenciados pelo Proxmox fora deste repositório. Em 12/10/2026, o proprietário confirmou que os backups são criptografados e que a restauração foi testada; a revisão registra esse controle como validado com base nessa confirmação operacional. Backups podem conter dados financeiros; não os envie ao GitHub, logs, tickets ou serviços sem autorização.

Antes de uma migration ou atualização que possa afetar dados, valide a recuperação conforme o procedimento do Proxmox e confira a revisão corrente:

```bash
docker compose -f docker-compose.yml -f docker-compose.vm.yml exec api alembic current
docker compose -f docker-compose.yml -f docker-compose.vm.yml exec api alembic upgrade head
```

Depois da atualização, confira `/api/health/live`, `/api/health/ready`, login e o Finance Engine. Preserve a imagem anterior até confirmar a operação; não reverta migrations destrutivas automaticamente.

## Publicar uma atualização do GitHub na VM

1. Revise a alteração, rode as verificações do componente e confirme `git diff --check`. Não inclua `.env`, arquivos de segredo, credenciais OAuth, backups ou dados financeiros no commit.
2. Publique o commit em branch/PR e aguarde sucesso do workflow `Qualidade e dependências` no SHA exato que será implantado, incluindo API, Frontend e runtime. Em 12/10/2026, uma consulta autenticada confirmou que `main` não tinha branch protection e o repositório não tinha rulesets; portanto, este gate é operacional e manual, não imposto pelo GitHub. Não implante SHA com CI pendente ou falha.
3. Faça merge/publicação do mesmo SHA validado em `main`. O deploy continua manual; nenhum workflow do repositório publica automaticamente na VM.
4. Na VM, preserve `.env` e `secrets/` locais e atualize somente o checkout: `git fetch origin` e `git pull --ff-only origin main`. Confira `git status --short` antes de construir; não descarte alterações locais sem identificar sua origem.
5. Valide e publique com `docker compose -f docker-compose.yml -f docker-compose.vm.yml config -q` e `docker compose -f docker-compose.yml -f docker-compose.vm.yml up -d --build --wait`.
6. Confira a revisão com `git rev-parse --short HEAD`, os seis serviços com `docker compose -f docker-compose.yml -f docker-compose.vm.yml ps`, a migration com `docker compose -f docker-compose.yml -f docker-compose.vm.yml exec api alembic current` e os dois health checks públicos. Não faça reset destrutivo do banco para atualizar o código.

## Comandos de operação

```bash
docker compose -f docker-compose.yml -f docker-compose.vm.yml ps
docker compose -f docker-compose.yml -f docker-compose.vm.yml logs --tail=100 cloudflared caddy web api worker postgres
docker compose -f docker-compose.yml -f docker-compose.vm.yml exec api alembic current
```

Os logs não devem conter senhas, token do túnel, token de bootstrap, códigos TOTP, cookies ou credenciais OAuth. Remova o token de primeiro acesso do `.env` assim que a conta for criada.
