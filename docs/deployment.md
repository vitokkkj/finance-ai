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
- Chave Fernet em `MFA_ENCRYPTION_KEY`, obrigatória para a API em produção. Siga o procedimento abaixo para gravá-la diretamente no `.env` sem exibi-la; mantenha uma cópia independente em um gerenciador de segredos ou backup offline protegido. Não gere outra chave a cada deploy: ela é necessária para descriptografar os autenticadores das contas gerenciadas.
- `MFA_ENROLLMENT_TOKEN` autoriza somente o primeiro pareamento do autenticador do proprietário. Gere com `openssl rand -hex 32`, use-o uma vez na tela privada do proprietário e remova a variável do `.env` após confirmar o código. Contas gerenciadas não usam esse token; cada pessoa inicia o pareamento com seu próprio e-mail e senha.
- Token aleatório e temporário para criar a primeira conta. Gere com `openssl rand -hex 32` e configure em `INITIAL_SETUP_TOKEN` somente durante o bootstrap.
- O limitador combina endereço de origem e conta, mas fica em memória e reinicia junto com a API. A regra de borda da Cloudflare cobre os POSTs de login, bootstrap e pareamento MFA. Não substitua o limitador da API por essa regra: ela agrega requisições por IP e existe como defesa adicional.
- `POSTGRES_PASSWORD` aleatória, com letras e números para evitar codificação especial na URL do banco.

Não reutilize valores de desenvolvimento do `.env.example` em produção. Não cole tokens, senhas, códigos TOTP, cookies ou credenciais OAuth no chat, em issues, logs ou workflows.

### Provisionar a chave Fernet sem exibi-la

Execute como `root` na VM, no diretório do projeto, apenas se `MFA_ENCRYPTION_KEY` ainda não tiver valor. O script gera a chave no processo, atualiza `.env` atomicamente e não imprime o segredo. Se já existir uma chave, preserve-a; não gere outra durante um deploy.

```bash
cd /opt/sophia-test
python3 - <<'PY'
import base64
import os
import secrets
from pathlib import Path

path = Path(".env")
lines = path.read_text().splitlines()
indexes = [i for i, line in enumerate(lines) if line.startswith("MFA_ENCRYPTION_KEY=")]
if len(indexes) > 1:
    raise SystemExit("Há mais de uma variável MFA_ENCRYPTION_KEY; corrija manualmente")
if indexes and lines[indexes[0]].partition("=")[2]:
    raise SystemExit("A chave já está configurada; ela não será substituída")

key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
line = "MFA_ENCRYPTION_KEY=" + key
if indexes:
    lines[indexes[0]] = line
else:
    lines.append(line)
temporary = path.with_name(".env.mfa.tmp")
fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as stream:
    stream.write("\n".join(lines) + "\n")
os.chown(temporary, 0, 0)
os.chmod(temporary, 0o600)
os.replace(temporary, path)
os.chown(path, 0, 0)
os.chmod(path, 0o600)
print("MFA_ENCRYPTION_KEY configurada; valor não exibido")
PY
stat -c '%a %U:%G .env' .env
```

Transfira a chave para o cofre do proprietário por um canal seguro e independente da VM e do banco. Confirme que o backup pode ser recuperado antes de considerar a proteção contra perda concluída. Não a inclua em comandos gravados no histórico, em capturas de tela ou nesta documentação.

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

A migration `0011_public_auth_hardening` revoga sessões antigas para exigir novo login. A migration `0012_owner_mfa_enrollment` adiciona apenas o estado e o prazo temporário de pareamento. A migration `0016_totp_replay` acrescenta o contador de códigos já consumidos e impede que o mesmo código abra sessões ou autorize novamente uma ação sensível. A migration `0017_financial_idempotency` introduziu os campos de idempotência nos movimentos. A migration `0018_idempotency_tombstones` cria uma tabela separada, preserva as chaves existentes e mantém a garantia de não duplicar uma operação depois da exclusão explícita do movimento; não remove nem altera lançamentos financeiros. As migrations `0017` e `0018` estão aplicadas na VM; `0018_idempotency_tombstones` era o head antes das publicações documentadas abaixo. O downgrade de `0018` é bloqueado; uma reversão exige restaurar um backup validado, não apagar a tabela manualmente. A compatibilidade de leitura/gravação com as colunas de `0017` cobre retries feitos durante um rollback de imagem, enquanto o movimento original ainda existir. Não mantenha uma versão anterior atendendo exclusões financeiras depois de `0018`: ela não preserva tombstones ao apagar a linha; nesse cenário, restaure também o banco do backup junto com a imagem anterior.

O PR de MFA individual e paginação passou migrations PostgreSQL (`alembic upgrade head` e `alembic check`) no CI `38326869097`; o PR #6 foi mesclado como `9079acc` e os três jobs passaram no SHA de `main` em `38327681278`. A migration `0019_managed_user_totp` adiciona o campo nullable do segredo TOTP cifrado; não altera dados financeiros e seu downgrade é bloqueado para evitar apagar autenticadores. A migration `0020_transaction_cursor_index` adiciona o índice da paginação. A cadeia `0018 → 0019 → 0020` foi validada no CI e aplicada na VM; `0020_transaction_cursor_index` era o head antes da migration `0021_mfa_pending_secret`, que agora é o head atual. A chave `MFA_ENCRYPTION_KEY` foi gerada diretamente na VM e está configurada em `/opt/sophia-test/.env`, `root:root`, modo `0600`; o valor não foi exibido nem armazenado no repositório. O proprietário confirmou uma cópia independente em cofre protegido; o teste de recuperação continua pendente.

O banco guarda os segredos TOTP individuais cifrados, mas não contém a chave `MFA_ENCRYPTION_KEY`; backups PostgreSQL sem essa chave não conseguem restaurar os autenticadores. O proprietário confirmou uma cópia independente da chave em cofre protegido; ainda falta testar a recuperação em ambiente controlado. A rotação da chave Fernet continua manual e exige re-cifrar cada segredo em uma operação controlada, validar os logins e manter o backup anterior até confirmar o resultado. Trocar o TOTP de uma conta é uma operação diferente: não troca a chave Fernet.

Com a migration `0021_mfa_pending_secret`, a pessoa pode abrir **Minha conta → Proteção da conta → Trocar autenticador**. A operação exige sessão ativa, senha e um código TOTP atual ainda não usado. A SophIA exibe um QR e uma chave TOTP temporária por dez minutos; o autenticador atual continua ativo até a confirmação do código novo. Ao confirmar, o novo TOTP substitui o anterior e todas as sessões dessa conta são encerradas. Em caso de cancelamento ou expiração, o TOTP atual permanece válido. O valor `MFA_ENCRYPTION_KEY` protege os segredos no servidor; não deve ser cadastrado no Authy. Para configurar um Authy, use o QR ou a chave temporária exibida durante esse fluxo.

`mfa_secret_encrypted` guarda o TOTP ativo e, durante a troca, `mfa_pending_secret_encrypted` guarda o próximo segredo cifrado. Para contas já cadastradas antes da primeira troca do proprietário, o TOTP existente continua vindo de `OWNER_TOTP_SECRET` até a rotação ser confirmada. Depois da troca, o segredo ativo do proprietário depende da `MFA_ENCRYPTION_KEY`; mantenha cópias compatíveis da chave e do banco. Em caso de perda da chave, restaure a chave original do cofre ou siga um procedimento de recuperação validado; não substitua a chave sem re-cifrar os segredos.

### Publicação anterior confirmada em 12/10/2026

A VM foi atualizada manualmente para o commit `01488a4c161fedac7444d1885b2b0b177a2bd546`, depois de CI verde no [workflow 38312160754](https://github.com/vitokkkj/finance-ai/actions/runs/38312160754). O Alembic reporta `0017_financial_idempotency (head)`. Os seis serviços do Compose estão ativos; API, PostgreSQL e web estão saudáveis. Os endpoints públicos `/api/health/live` e `/api/health/ready` retornaram `200`; `/api/accounts` e `/api/admin/users`, sem sessão, retornaram `401`; `/api/docs` retornou `404`. Durante a recriação dos containers, o Caddy respondeu `502` enquanto o serviço web iniciava; depois que o Next.js ficou pronto, os health checks públicos foram repetidos e passaram.

Antes da migration foi criado um dump PostgreSQL temporário com permissão `0600`; o cabeçalho e a listagem de restauração foram validados sem ler registros. Após a aplicação e os health checks, esse arquivo temporário foi removido e a ausência confirmada. A retenção de backup continua no Proxmox, fora do repositório.

### Atualização de idempotência confirmada em 12/10/2026

Com autorização do proprietário, a VM em `/opt/sophia-test` foi atualizada para o SHA `41368d93bd96c4e1814890d29110323fbec5e864`, depois de todos os jobs do [workflow 38317703475](https://github.com/vitokkkj/finance-ai/actions/runs/38317703475) passarem. A CI validou lint e tipos, migrations e testes PostgreSQL, E2E Playwright, auditorias de dependências, Compose e builds de produção. O `docker compose ... up -d --build --wait` concluiu; seis serviços estão ativos, com API, web e PostgreSQL saudáveis. O Alembic reporta `0018_idempotency_tombstones (head)`.

Pelo hostname HTTPS, `/api/health/live` e `/api/health/ready` responderam `200`; `/api/accounts` e `/api/admin/users`, sem sessão, responderam `401`; `/api/docs` respondeu `404`. A resposta de readiness incluiu HSTS, CSP, `X-Content-Type-Options`, `X-Frame-Options`, Referrer-Policy e Permissions-Policy. Inspeção de `NetworkSettings.Ports` confirmou que API, web, PostgreSQL e Caddy não publicam portas no host. O SSH permaneceu ativo; `sshd -T` confirmou `PasswordAuthentication yes`, `PermitRootLogin without-password`, `PubkeyAuthentication yes`, `KbdInteractiveAuthentication no` e `AllowUsers sophia`/`root`.

Antes da migration foi criado um dump custom PostgreSQL temporário de 143.674 bytes, modo `0600`, sem criptografia. `pg_restore --list` passou dentro do container PostgreSQL; o arquivo foi removido após as checagens e sua ausência confirmada. A máquina tinha 8,7 GB livres de 40 GB e 7,3 GiB de memória disponível após o deploy. Não foram lidos registros financeiros, `.env` ou segredos. O host não tinha `pg_restore` instalado, então a listagem foi validada pela ferramenta do container.

Na zona `ruralflow.com.br`, a regra ativa **Autenticacao - limite por IP** corresponde ao host `finance.ruralflow.com.br`, método `POST` e às rotas `/api/auth/setup`, `/api/auth/login/check`, `/api/auth/login`, `/api/auth/mfa/enrollment/start` e `/api/auth/mfa/enrollment/confirm`. Ela conta por IP e bloqueia por 10 segundos depois de mais de 20 requisições em 10 segundos. A regra foi validada pelo Cloudflare e aparece ativa; não foi gerado tráfego de força bruta para testá-la em produção. Na inspeção de 12/10/2026, o plano Free mostrava `1/1` regras de rate limit em uso; consolide futuras rotas nesta regra ou revise o plano antes de adicionar outra.

### Publicação de MFA individual e paginação em 12/10/2026

PR [#6](https://github.com/vitokkkj/finance-ai/pull/6) foi mesclado após os três checks obrigatórios passarem em `38327392851`. O commit `9079acc0da289099c44c362362c1dabfa20bc4fa` passou nos três jobs do CI de `main`, run [38327681278](https://github.com/vitokkkj/finance-ai/actions/runs/38327681278), antes do deploy manual. A VM em `/opt/sophia-test` avançou em fast-forward de `41368d9` para `9079acc`, sem alterações locais. `docker compose ... config -q` passou e `up -d --build --wait` concluiu.

As migrations `0019_managed_user_totp` e `0020_transaction_cursor_index` foram aplicadas; Alembic reportou `0020_transaction_cursor_index (head)`. A chave Fernet foi gerada na VM e adicionada a `.env` sem exibição; o arquivo tem proprietário `root:root` e modo `0600`. Naquela publicação, a cópia independente ainda não havia sido confirmada; o proprietário confirmou depois que a guardou em cofre protegido. O teste de recuperação continua pendente.

Os seis serviços Compose estão ativos; API, web e PostgreSQL ficaram saudáveis. Nenhum serviço publica porta no host. No hostname HTTPS, live/ready retornaram `200`, `/api/accounts` e `/api/admin/users` sem sessão retornaram `401`, e `/api/docs` retornou `404`. HSTS, CSP, `X-Content-Type-Options`, `X-Frame-Options`, Referrer-Policy e Permissions-Policy foram conferidos. O SSH permaneceu ativo com senha para `sophia`, `su -` mantido, root por chave e TCP/22 aberto. O dump custom pré-deploy tinha 147.749 bytes, foi validado com `pg_restore --list` dentro do container e removido após as checagens. O disco ficou com 8,5 GB livres de 40 GB. Nenhum registro financeiro ou valor de segredo foi aberto.

### Troca do autenticador próprio — publicada em 12/10/2026

O PR [#9](https://github.com/vitokkkj/finance-ai/pull/9) foi mesclado como `14e99370a54f5e46f112093698ff24674e942fdc` após os três jobs passarem no CI do PR (`38332105668`) e no CI de `main` (`38332335587`). A VM em `/opt/sophia-test` avançou por fast-forward de `9079acc` para `14e9937`; a configuração do Compose passou e `up -d --build --wait` concluiu. Alembic reportou `0021_mfa_pending_secret (head)` e os seis serviços estavam ativos.

Antes da migration, um dump PostgreSQL custom de 147.964 bytes foi criado como `root`, modo `0600`, e sua listagem foi validada por `pg_restore --list` dentro do container. O dump temporário foi removido após as verificações. No hostname HTTPS, `/api/health/live` e `/api/health/ready` retornaram `200`; `/api/accounts` e `/api/admin/users`, sem sessão, retornaram `401`; `/api/docs` retornou `404`. Foram conferidos HSTS, CSP, `X-Content-Type-Options`, `X-Frame-Options`, Referrer-Policy e Permissions-Policy. O deploy não alterou o TOTP ativo do proprietário; para gerar o QR, ele precisa iniciar a troca na própria conta.

### Navegação dos editores e alinhamento das categorias — publicados em 13/10/2026

O PR [#11](https://github.com/vitokkkj/finance-ai/pull/11) foi mesclado como `0841b9742950f8e70617aee63de801486f575902` após os três jobs passarem no CI do PR (`38389132032`) e no CI de `main` (`38389505295`). A VM em `/opt/sophia-test` avançou por fast-forward de `14e9937` para `0841b97`, sem alterações locais. A configuração do Compose passou e `up -d --build --wait` concluiu; os seis serviços ficaram ativos.

Não houve migration nem alteração de dados financeiros; Alembic permaneceu em `0021_mfa_pending_secret (head)`, por isso não foi criado dump temporário nesta atualização. No domínio HTTPS, `/api/health/live` e `/api/health/ready` retornaram `200`, `/api/accounts` sem sessão retornou `401` e `/api/docs` retornou `404`. A resposta de readiness incluiu CSP, HSTS, Permissions-Policy, Referrer-Policy, `X-Content-Type-Options` e `X-Frame-Options`. A validação não abriu registros financeiros, `.env` ou segredos.

### Gesto lateral do menu no iPhone — publicado em 13/10/2026

O PR [#13](https://github.com/vitokkkj/finance-ai/pull/13) foi mesclado como `ff69605334d1fc438cf0365cecce1deed422c817` após os três jobs passarem no CI do PR (`38459553876`) e no CI de `main` (`38459995535`). A VM em `/opt/sophia-test` avançou por fast-forward de `0841b97` para `ff69605`, sem alterações locais. `docker compose ... config -q` passou e `up -d --build --wait` concluiu; os seis serviços ficaram ativos, com web, API e PostgreSQL saudáveis.

Não houve migration nem alteração de dados financeiros; Alembic permaneceu em `0021_mfa_pending_secret (head)`, então não foi criado dump temporário. No domínio HTTPS, `/api/health/live` e `/api/health/ready` retornaram `200`, `/api/accounts` sem sessão retornou `401` e `/api/docs` retornou `404`. O serviço SSH permaneceu ativo. A correção limita o gesto nativo de voltar do Safari à faixa em que o drawer da aplicação abre; os controles Voltar/Avançar do navegador continuam disponíveis.

### Atalho de compra no cartão em Lançamentos — publicado em 14/10/2026

O PR [#15](https://github.com/vitokkkj/finance-ai/pull/15) foi mesclado no commit `ad69ca4753f719d73ab0831f1b4c2ad2f53651a3` após os três checks (`API`, `Frontend` e `Imagens e perfil público`) passarem no CI do PR ([workflow 38612627497](https://github.com/vitokkkj/finance-ai/actions/runs/38612627497)) e no CI de `main` ([workflow 38613109259](https://github.com/vitokkkj/finance-ai/actions/runs/38613109259)). A VM em `/opt/sophia-test` avançou por fast-forward de `ff69605` para `ad69ca4`. Em **Lançamentos**, o botão **Compra no cartão** leva ao formulário **Registrar compra** em **Cartões**, abre e foca o formulário existente. A compra continua vinculada à fatura e entra no histórico unificado; não houve mudança de regra financeira nem de API.

O deploy não incluiu migration nem alteração de dados financeiros; Alembic permaneceu em `0021_mfa_pending_secret (head)`. O Compose validou com `config -q` e a construção/publicação concluiu com `up -d --build --wait`; os seis serviços ficaram saudáveis. A primeira chamada remota enviada como script por SSH respondeu `unknown flag` antes de recriar containers; o checkout já estava atualizado, os containers anteriores foram confirmados ativos e saudáveis, e a execução direta do mesmo comando de Compose concluiu. A causa da primeira resposta não foi determinada.

Após o deploy, `/api/health/live` e `/api/health/ready` retornaram `200`; `/api/accounts` e `/api/admin/users`, sem sessão, retornaram `401`; `/api/docs` retornou `404`. Foram confirmados HSTS, CSP, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, Referrer-Policy e Permissions-Policy. API, web, PostgreSQL e Caddy não publicam portas no host. O serviço SSH permaneceu ativo com a política já aprovada: senha para `sophia`, root somente por chave e `AllowUsers sophia root`. Nenhuma migration, `.env`, credencial ou registro financeiro foi aberto durante a verificação.

### Login móvel e tabelas financeiras — publicados em 16/10/2026

O PR [#17](https://github.com/vitokkkj/finance-ai/pull/17) foi mesclado como `9e4dcbe0573b9815f4f860ec727adba1f21531ae` após os três checks obrigatórios — `API`, `Frontend` e `Imagens e perfil público` — passarem no PR (workflow `38951965641`) e no CI de `main` (workflow `38952398989`). A correção define fonte mínima de 16 px nos campos móveis para evitar zoom automático no Safari e reorganiza contas, categorias, lançamentos, cartões e faturas em cartões rotulados que mostram todos os valores sem arraste horizontal. Foram adicionados cenários E2E para login e listagens em 390 px.

A VM em `/opt/sophia-test` avançou por fast-forward de `ad69ca4` para `9e4dcbe`. `docker compose ... config -q` passou e `up -d --build --wait` concluiu; web, API e PostgreSQL ficaram saudáveis, e os seis serviços estavam ativos. Não houve alteração de API ou migration; Alembic permaneceu em `0021_mfa_pending_secret (head)` e não foi criado dump temporário. O checkout estava limpo antes do deploy e a configuração SSH permaneceu inalterada.

Após o deploy, GET `/api/health/live` e `/api/health/ready` retornaram `200`; `/api/accounts`, sem sessão, retornou `401`; `/api/docs` retornou `404`. Foram observados HSTS, CSP, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, Referrer-Policy e Permissions-Policy. A validação automatizada de viewport passou em Chromium; confirmar o zoom e a rolagem no Safari/iPhone real continua pendente.

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
2. Publique o commit em branch/PR e aguarde sucesso do workflow `Qualidade e dependências` no SHA exato que será implantado, incluindo `API`, `Frontend` e `Imagens e perfil público`. Desde 12/10/2026, o ruleset ativo `24959980` exige PR e esses três checks para `main`, com política estrita, sem aprovação humana, bypass, exclusão ou force-push. Não implante SHA com CI pendente ou falha.
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

### Otimização de latência da IA — publicada em 16/10/2026

O PR [#19](https://github.com/vitokkkj/finance-ai/pull/19) foi mesclado no commit `b309b5b87bb288e05af28861038fd31452bd290b`. Os checks do PR passaram no workflow [38956609979](https://github.com/vitokkkj/finance-ai/actions/runs/38956609979) e os checks de `main` passaram no workflow [38957027235](https://github.com/vitokkkj/finance-ai/actions/runs/38957027235), incluindo API/PostgreSQL, E2E Chromium, auditoria de dependências, lint, tipos e build.

A VM `/opt/sophia-test` avançou por fast-forward de `4d2aa3a` para `b309b5b`. `docker compose ... config -q` e `up -d --build --wait` passaram; os seis serviços ficaram ativos, com API, web e PostgreSQL saudáveis. `/api/health/live` e `/api/health/ready` retornaram `200`, `/api/accounts` sem sessão retornou `401` e `/api/docs` retornou `404`. Alembic permaneceu em `0021_mfa_pending_secret (head)`; não houve migration nem alteração de dados financeiros. A comparação de latência pós-publicação ainda depende de novas respostas do proprietário.

### Indicador de pensamento no computador — publicado em 16/10/2026

O PR [#21](https://github.com/vitokkkj/finance-ai/pull/21) foi mesclado como `1dd032b91f78a07397420b103a4dbfda64f4ab68`. Os três checks passaram no workflow do PR [38958304851](https://github.com/vitokkkj/finance-ai/actions/runs/38958304851) e no workflow de `main` [38958720024](https://github.com/vitokkkj/finance-ai/actions/runs/38958720024), incluindo E2E Chromium, lint, tipos e build. O teste E2E confirma a rotação de 1,2 s do indicador quando `prefers-reduced-motion` está ativo; as demais animações continuam reduzidas.

A VM `/opt/sophia-test` avançou por fast-forward de `b309b5b` para `1dd032b`. O Compose passou na validação e `up -d --build --wait`; os seis serviços ficaram ativos, com API, web e PostgreSQL saudáveis. `/api/health/live` e `/api/health/ready` retornaram `200`, `/api/accounts` sem sessão retornou `401` e `/api/docs` retornou `404`. Alembic continuou em `0021_mfa_pending_secret (head)`; não houve migration nem alteração de dados financeiros.

### Histórico de conversas com carregamento progressivo — publicado em 16/10/2026

O PR [#23](https://github.com/vitokkkj/finance-ai/pull/23) foi mesclado como `8eb4457`. Os três checks obrigatórios passaram no workflow [38963966479](https://github.com/vitokkkj/finance-ai/actions/runs/38963966479), incluindo API, E2E de frontend e build de produção. A barra lateral passou a exibir dez conversas recentes e o botão **Carregar mais** acrescentava até dez por vez; a conversa ativa permanecia visível quando já estava em um grupo mais antigo. Essa interface inicial foi substituída pelo carregamento automático na atualização seguinte.

A VM `/opt/sophia-test` avançou por fast-forward de `38e47f0` para `8eb4457`. `docker compose ... config -q` e `up -d --build --wait` passaram. Os seis serviços ficaram ativos; API, web e PostgreSQL estavam saudáveis. `/api/health/live` e `/api/health/ready` retornaram `200`, `/api/accounts` sem sessão retornou `401` e `/api/docs` retornou `404`. Alembic permaneceu em `0021_mfa_pending_secret (head)`; não houve migration nem alteração de dados financeiros.

### Histórico de conversas com carregamento automático — publicado em 16/10/2026

O PR [#25](https://github.com/vitokkkj/finance-ai/pull/25) foi mesclado no commit `a516ded0aa6a2c46a0878a0723431690d6f500a5`. Os três checks obrigatórios passaram no workflow [38965578838](https://github.com/vitokkkj/finance-ai/actions/runs/38965578838), incluindo API, E2E do frontend e build das imagens. A barra lateral mostra dez conversas no início e acrescenta automaticamente até dez quando a pessoa rola perto do fim; um anúncio acessível informa o progresso para leitores de tela.

A VM `/opt/sophia-test` avançou por fast-forward de `592ecd2` para `a516ded`. `docker compose ... config -q` e `up -d --build --wait` passaram. Os seis serviços ficaram ativos; API, web e PostgreSQL estavam saudáveis. `/api/health/live` e `/api/health/ready` retornaram `200`, `/api/accounts` sem sessão retornou `401` e `/api/docs` retornou `404`. Alembic permaneceu em `0021_mfa_pending_secret (head)`; não houve migration nem alteração de dados financeiros.

### Redução do contexto da IA e métricas de latência — publicada em 19/10/2026

O PR [#31](https://github.com/vitokkkj/finance-ai/pull/31) foi mesclado no SHA `372675db7170f8930808093003e82141f8bc51cf`. Os três checks passaram no workflow do PR [39241797392](https://github.com/vitokkkj/finance-ai/actions/runs/39241797392) e no workflow da `main` [39242170794](https://github.com/vitokkkj/finance-ai/actions/runs/39242170794), incluindo migrations PostgreSQL, testes da API, E2E Chromium, auditoria de dependências e construção das imagens.

Em consultas simples e inequívocas de leitura no primeiro turno, a API envia só as ferramentas pertinentes: a consulta “quanto gastei este mês?” passa de 24 ferramentas e 16.972 caracteres de esquemas para 6 ferramentas e 3.869 caracteres; saldo passa para 3 ferramentas e 1.366 caracteres; faturas para 5 ferramentas e 2.854 caracteres. Escritas, pedidos mistos/complexos e continuações mantêm o catálogo completo. A migration `0022_ai_latency_diagnostics` adiciona tempos de preparação, primeira saída do provider, primeiro texto e quantidade de ferramentas. Ela não altera registros financeiros.

Antes da migration, um dump temporário de 180.944 bytes foi criado no host com modo `0600`, validado por `pg_restore --list` no container PostgreSQL e removido do host e do container. A VM avançou por fast-forward de `c335bda` para `372675d`; o checkout ficou limpo, os seis serviços ficaram saudáveis e Alembic chegou a `0022_ai_latency_diagnostics (head)`. `/api/health/live` e `/api/health/ready` retornaram `200`, `/api/accounts` sem sessão retornou `401` e `/api/docs` retornou `404`. Nenhum lançamento ou saldo foi alterado.

A redução do contexto foi medida localmente pelo tamanho dos esquemas; a diferença de latência nas respostas reais ainda precisa ser observada. Os novos tempos são persistidos sem conteúdo da conversa e aparecem no painel de diagnóstico apenas em `APP_ENV=development`.

### Diagnóstico pós-publicação da latência — 20/10/2026

Uma leitura somente de metadados das duas respostas do proprietário após a publicação de 19/10 mostrou durações de `15.190 ms` e `15.854 ms`, texto visível após `14.132 ms` e `14.952 ms`, preparação local de `27 ms` e `37 ms`, e 24 ferramentas oferecidas em cada turno. Cada resposta percorreu três rodadas sequenciais do modelo para resolver dados financeiros e registrar uma despesa. O conteúdo, os argumentos e as saídas das conversas não foram consultados. A amostra de duas respostas é pequena e não representa a latência geral, mas indica que a preparação local não é o gargalo e que a redução anterior de ferramentas não alcançou esses pedidos de escrita.

A melhoria seguinte estende o parser determinístico para o formato explícito de valor, descrição e categoria, por exemplo `15 em Bolo, lançar em Lanche`. O PR [#34](https://github.com/vitokkkj/finance-ai/pull/34) foi mesclado no SHA `99175c9ea60cb401b4a970a16b153c7120a5af43`; os workflows do PR [39412151138](https://github.com/vitokkkj/finance-ai/actions/runs/39412151138) e da `main` [39412576394](https://github.com/vitokkkj/finance-ai/actions/runs/39412576394) passaram, incluindo PostgreSQL e E2E. A VM avançou de `372675d` para `99175c9`; um dump temporário de `184.365` bytes foi validado e removido. Os seis serviços ficaram saudáveis, os health checks públicos retornaram `200`, `/api/accounts` sem sessão retornou `401`, `/api/docs` retornou `404` e Alembic permaneceu em `0022_ai_latency_diagnostics (head)`. Não houve migration nem alteração de lançamentos durante o deploy.

O parser só grava quando a categoria de despesa e a conta podem ser resolvidas sem ambiguidade; cartão, categoria não encontrada e múltiplas contas continuam exigindo esclarecimento ou o fluxo do modelo. O restante dos pedidos mantém o mesmo modelo e as mesmas regras financeiras. O ganho de latência desse caminho ainda precisa ser medido após novas utilizações.

### Correção de troca de categoria e dependência Pillow — publicada em 21/10/2026

O PR [#36](https://github.com/vitokkkj/finance-ai/pull/36) foi mesclado no SHA `7ae38608ebd9f304ae3d9f3ce160227bb6da4327`. Os três checks passaram no workflow do PR [39601539696](https://github.com/vitokkkj/finance-ai/actions/runs/39601539696) e no workflow de `main` [39602106638](https://github.com/vitokkkj/finance-ai/actions/runs/39602106638), incluindo testes PostgreSQL, E2E, lint, tipos, build de imagens e auditorias de dependências.

O assistente agora associa “Lançar em outra categoria” ao único lançamento comum exibido na resposta anterior, pede uma categoria ativa do mesmo tipo e mantém a confirmação antes de gravar. A prévia usa o nome da categoria; o UUID segue somente na entrada interna da confirmação. Esse fluxo evita rodadas do modelo para identificar o lançamento e resolver o nome, mas a latência real dessa mudança ainda precisa ser observada. A dependência Pillow foi atualizada de `12.3.0` para `13.0.0` após a auditoria do CI apontar oito advisories na versão anterior; a [versão 13.0.0 registra correções de segurança](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html). A auditoria Python passou nos checks finais.

A VM `/opt/sophia-test` avançou por fast-forward de `99175c9` para `7ae3860`, com checkout limpo. `docker compose ... config -q` e `up -d --build --wait` passaram; API, web e PostgreSQL ficaram saudáveis e os seis serviços permaneceram ativos. Alembic continuou em `0022_ai_latency_diagnostics (head)`; não houve migration nem alteração de dados financeiros. `/api/health/live` e `/api/health/ready` retornaram `200`, `/api/accounts` sem sessão retornou `401` e `/api/docs` retornou `404`. HSTS, CSP, `X-Content-Type-Options`, `X-Frame-Options`, Referrer-Policy e Permissions-Policy foram conferidos.

### Totais de filtros e respostas financeiras da SophIA — publicados em 25/10/2026

O PR [#46](https://github.com/vitokkkj/finance-ai/pull/46) foi mesclado no SHA `d33e25a104c4d42f06e26ca1ae2b77507260c001`. Os checks de API, Frontend e imagens/perfil público passaram no workflow do PR [40206382499](https://github.com/vitokkkj/finance-ai/actions/runs/40206382499) e no CI de `main` [40206647509](https://github.com/vitokkkj/finance-ai/actions/runs/40206647509).

`GET /api/transactions` calcula no banco os totais decimais para todo o conjunto que corresponde aos filtros, independentemente da página visível. A tela **Lançamentos** mostra a quantidade completa e os valores correspondentes. As ferramentas `get_transactions` e `search_transactions` entregam o mesmo resumo ao modelo; a SophIA deve responder perguntas de soma usando os valores do Finance Engine, sem somar itens manualmente. Despesas incluem compras no cartão; transferências próprias e pagamentos de fatura ficam separados. Os filtros e o assistente continuam vinculados ao usuário da sessão. Não houve mudança no schema nem migration.

O frontend foi atualizado do Next.js `16.4.0` para `16.4.1`. O fornecedor marcou `16.4.0` como afetado por duas vulnerabilidades críticas, incluindo execução remota de código; `16.4.1` é a versão corrigida ([advisory de `use cache`](https://github.com/vercel/next.js/security/advisories/GHSA-673q-mjm6-r5xr), [advisory de Image Optimization](https://github.com/vercel/next.js/security/advisories/GHSA-2464-fhr4-w9xw)). A auditoria npm encontrou zero vulnerabilidades após a atualização.

A VM `/opt/sophia-test` avançou de `7ae3860` para `d33e25a`. `docker compose ... config -q` e `up -d --build --wait` passaram; os seis serviços permaneceram ativos e API, web e PostgreSQL ficaram saudáveis. A versão `next@16.4.1` foi conferida dentro do container web. Alembic continuou em `0022_ai_latency_diagnostics (head)`. Os endpoints `/api/health/live` e `/api/health/ready` retornaram `200`, `/api/accounts` sem sessão retornou `401`, `/api/docs` retornou `404` e a página principal retornou `200`. Não houve migration nem alteração de lançamentos ou saldos.

Na primeira chamada de deploy, o pull avançou o checkout, mas uma verificação shell local falhou por expansão de aspas (`test: too many arguments`) antes de qualquer recriação de serviço. O comando Compose foi executado em seguida sem essa verificação e concluiu o deploy; os health checks acima confirmaram a recuperação normal. A API local passou com 224 testes e 3 skips condicionados ao ambiente; a E2E local passou com 30 testes e 1 skip integrado. O CI PostgreSQL e E2E integrado passou. O lint local mantém quatro avisos anteriores de `!important` em `editorial-design.css`.

### Ganhos por dia em consultas de receitas — publicados em 25/10/2026

O PR [#48](https://github.com/vitokkkj/finance-ai/pull/48) foi mesclado no SHA `7f484a90bd8e5bf37c557950a16ee65303b29be5`. O workflow do PR [40210490087](https://github.com/vitokkkj/finance-ai/actions/runs/40210490087) passou. No CI de `main`, o primeiro job foi cancelado durante o E2E após demora na instalação do Chromium; a reexecução completa [40210775114](https://github.com/vitokkkj/finance-ai/actions/runs/40210775114) terminou com os três jobs verdes: API/PostgreSQL, Frontend com E2E integrado, auditoria npm, lint, tipos e build, e imagens/perfil público.

Consultas de receitas com intervalo de datas de até 62 dias agora podem incluir os totais de cada dia, agrupados pela data financeira em `America/Sao_Paulo` e calculados no banco usando valores decimais. O resumo diário é opcional para outras consultas. A interface mostra os ganhos por dia e normaliza dados estruturados aninhados das respostas para evitar cartões de lançamento genéricos sem valores. A IA continua usando o Finance Engine, sem somar valores manualmente. Não houve mudança no schema.

A VM `/opt/sophia-test` avançou por fast-forward de `d33e25a` para `7f484a9`. `docker compose ... config -q`, a construção separada das imagens e `up -d` passaram. Os seis serviços estão ativos; API, web e PostgreSQL estão saudáveis. Alembic permanece em `0022_ai_latency_diagnostics (head)`, sem migration ou alteração de lançamentos e saldos. `/api/health/live`, `/api/health/ready` e a página principal retornaram `200`; `/api/accounts` sem sessão retornou `401` e `/api/docs` retornou `404`.

Na primeira tentativa de acionamento remoto, a combinação de flags de build/espera foi rejeitada antes da recriação dos serviços. As imagens foram então construídas em etapa separada e o Compose iniciou os serviços; a checagem final confirmou a revisão e a saúde esperadas. Não houve interrupção persistente, migration ou alteração de dados financeiros.

### Redesign visual unificado da SophIA — publicado em 25/10/2026

O PR [#50](https://github.com/vitokkkj/finance-ai/pull/50) foi mesclado no commit `d39bddc`. Os três jobs obrigatórios — API, Frontend e Imagens e perfil público — passaram no workflow [40255150478](https://github.com/vitokkkj/finance-ai/actions/runs/40255150478). A suíte Frontend incluiu E2E integrado, auditoria npm, lint, tipos e build; a imagem web de produção também foi construída no CI.

A interface de login, chat, navegação, telas financeiras, preferências e conta agora compartilha a direção visual verde inspirada no template AI Chat da TailGrids, adaptada aos componentes e fluxos reais da SophIA. O processamento do chat usa um orbe CSS vinculado ao estado real da API, respeita `prefers-reduced-motion` e não introduz espera artificial nem resposta fictícia. O tema da barra do navegador acompanha a opção claro/escuro. A rota de prévia com dados demonstrativos foi removida. Não houve mudança em autenticação, permissões, cálculos financeiros ou API.

A VM `/opt/sophia-test` avançou por fast-forward de `7f484a9` para `d39bddc`, sem alterações locais. `docker compose ... config -q` e `up -d --build --wait` concluíram; os seis serviços ficaram ativos, com API, web e PostgreSQL saudáveis. `/api/health/live` e `/api/health/ready` retornaram `200`; `/api/accounts` sem sessão retornou `401`; `/api/docs` retornou `404`. Alembic permaneceu em `0022_ai_latency_diagnostics (head)`. Não houve migration nem alteração de lançamentos ou saldos.

O primeiro workflow do PR identificou um sufixo CSS inválido (`\n`) na construção da imagem web; ele foi removido e o segundo workflow completo passou. A primeira chamada remota de deploy também terminou antes da ação dos containers porque os finais de linha CRLF anexaram um caractere à opção `--wait`. O script foi normalizado para LF e executado novamente. O serviço anterior permaneceu no ar durante as duas correções; não houve interrupção persistente.

As verificações locais passaram: 31 testes E2E e um teste integrado ignorado por depender do ambiente do CI, lint, typecheck e build. O lint ainda informa quatro avisos `!important` preexistentes em `editorial-design.css`.

### Polimento do chat e varredura E2E móvel — publicado em 26/10/2026

O PR [#52](https://github.com/vitokkkj/finance-ai/pull/52) foi mesclado no commit `2a3acc04c22754b9a37a328edf0e533323a735f9`. Os três checks passaram no workflow do PR [40313361315](https://github.com/vitokkkj/finance-ai/actions/runs/40313361315) e no CI de `main` [40313862394](https://github.com/vitokkkj/finance-ai/actions/runs/40313862394), incluindo API/PostgreSQL, E2E integrado, auditoria npm, lint, tipos e build de produção.

O aro externo do indicador tem rotação mais evidente e o teste verifica mudanças reais de transformação; aro, núcleo e ponto respeitam movimento reduzido. O ícone da conversa selecionada permanece contornado, o histórico ficou mais compacto, o rótulo desktop do menu não quebra em duas linhas e mensagens longas do usuário não ultrapassam o chat. A varredura Playwright percorreu chat, Visão geral, Lançamentos, Contas, Cartões, Programados, Categorias e Preferências em larguras de 360, 390 e 430 px, cobrindo overflow horizontal, posição do composer/drawer, histórico e quebra de mensagem. A suíte local terminou com 34 testes aprovados e 1 cenário integrado ignorado (executado no CI); lint, typecheck e build passaram. Permanecem quatro avisos preexistentes do Biome sobre `!important` em `editorial-design.css`. Safari em iPhone físico ainda não foi testado nesta rodada.

A VM `/opt/sophia-test` avançou por fast-forward de `d39bddc` para `2a3acc0`; o checkout estava limpo. `docker compose ... config -q` e `up -d --build --wait` concluíram. Os seis serviços estão ativos, com API, web e PostgreSQL saudáveis; Alembic permanece em `0022_ai_latency_diagnostics (head)`. `/`, `/api/health/live` e `/api/health/ready` retornaram `200`; `/api/accounts` sem sessão retornou `401`; `/api/docs` retornou `404`. Não houve migration, alteração de dados financeiros, falha de CI nem interrupção persistente durante a publicação.

### Histórico de conversas e contexto em chats antigos — publicado em 26/10/2026

O PR [#54](https://github.com/vitokkkj/finance-ai/pull/54) foi mesclado como `4a56e359e3728cac92289fba80413a8a94acff11`. Os três jobs obrigatórios passaram no CI do PR [40317874845](https://github.com/vitokkkj/finance-ai/actions/runs/40317874845) e no CI de `main` [40318485025](https://github.com/vitokkkj/finance-ai/actions/runs/40318485025), incluindo E2E integrado, auditorias, lint, typecheck e build.

O histórico da barra lateral mantém uma área rolável limitada em telas altas e no drawer móvel; ao chegar perto do fim, carrega mais conversas em lotes de dez. Chats antigos mantêm acesso ao resumo financeiro geral quando há dados disponíveis, mesmo quando o texto não corresponde ao classificador de assunto. Não houve mudança na API, no schema ou nos dados financeiros. O E2E local terminou com 36 aprovações e um teste integrado ignorado localmente; o cenário integrado passou na CI. O lint mantém quatro avisos preexistentes de `!important` em `editorial-design.css`.

A VM `/opt/sophia-test` avançou em fast-forward de `2a3acc0` para `4a56e35`, sem alterações locais. `docker compose -f docker-compose.yml -f docker-compose.vm.yml config -q` e `up -d --build --wait` passaram. Os seis serviços estão ativos; API, web e PostgreSQL saudáveis. Alembic permaneceu em `0022_ai_latency_diagnostics (head)`, sem migration ou alteração de saldos/lançamentos. `/`, `/api/health/live` e `/api/health/ready` retornaram `200`; `/api/accounts` sem sessão retornou `401`; `/api/docs` retornou `404`.

### Histórico/contexto e correção dos filtros — publicados em 26/10/2026

O PR [#56](https://github.com/vitokkkj/finance-ai/pull/56) foi mesclado como `4b25bde` após os três checks obrigatórios passarem no workflow [40335701070](https://github.com/vitokkkj/finance-ai/actions/runs/40335701070), incluindo a suíte E2E integrada. A alteração faz o histórico carregar conversas em lotes de dez até a divisória da navegação e organiza os grupos do painel financeiro para melhorar a leitura. A documentação visual foi atualizada no mesmo PR.

O PR [#57](https://github.com/vitokkkj/finance-ai/pull/57) foi mesclado como `3f6dbc4`. Os três checks passaram no workflow [40339534616](https://github.com/vitokkkj/finance-ai/actions/runs/40339534616). A regra de superfície dos controles foi alterada para `background-color`, preservando as propriedades da seta SVG dos filtros de lançamentos. O E2E confirma que os três seletores mantêm `background-repeat: no-repeat` e uma imagem de seta; a regra foi registrada em `docs/ui-design-system.md`.

A VM `/opt/sophia-test` avançou por fast-forward de `4b25bde` para `3f6dbc4`, com o checkout limpo. A configuração Compose foi validada e somente o serviço `web` foi reconstruído e recriado; API, PostgreSQL, worker, Caddy e Cloudflare Tunnel não foram alterados. Os seis serviços estão ativos; web, API e PostgreSQL saudáveis. Alembic permaneceu em `0022_ai_latency_diagnostics (head)`, sem migration ou alteração de dados financeiros. `/`, `/api/health/live` e `/api/health/ready` retornaram `200`; `/api/accounts` sem sessão retornou `401`; `/api/docs` retornou `404`.

### Compras parceladas, calendário móvel e ajustes do chat — publicado em 26/10/2026

O PR [#59](https://github.com/vitokkkj/finance-ai/pull/59) foi mesclado no commit `9a4d97214d1ad37ddd80321cd4df1863c09af570`. Os três jobs obrigatórios passaram no workflow [40366216658](https://github.com/vitokkkj/finance-ai/actions/runs/40366216658): testes e migrations PostgreSQL na API, Frontend com E2E integrado, lint, tipos, build e auditoria npm, além das imagens e configuração pública.

A SophIA agora registra compras parceladas no cartão em 2 a 36 parcelas, tanto pelo chat com prévia e confirmação explícita quanto pela aba **Cartões**. Cada parcela é uma transação ligada à fatura mensal correspondente; centavos residuais são distribuídos para que a soma corresponda exatamente ao total. A migration `0023_card_purchase_installments` foi aplicada. A seleção do mês na Visão Geral passou a permanecer fixa e visível em telas estreitas. O histórico inicial mostra no mínimo dez conversas e usa a altura livre da barra lateral; continua carregando lotes de dez. Os ícones das sugestões agora ficam centralizados e o resumo de saldo/gastos tem espaçamento interno.

As verificações locais focadas passaram: três E2Es para histórico desktop, drawer móvel, resumo e ícones; lint, typecheck e build. O lint continua mostrando quatro avisos preexistentes de `!important` em `editorial-design.css`. A suíte E2E integrada completa e os checks de API/PostgreSQL passaram no workflow do PR.

A VM `/opt/sophia-test` avançou em fast-forward de `3f6dbc4` para `9a4d972`, com checkout limpo após a publicação. `docker compose ... config -q` e `up -d --build --wait` passaram. Os seis serviços estão ativos; API, web e PostgreSQL aparecem saudáveis. Alembic está em `0023_card_purchase_installments (head)`. Pelo domínio público, `/`, `/api/health/live` e `/api/health/ready` retornaram `200`; `/api/accounts` sem sessão retornou `401`; `/api/docs` retornou `404`.

Antes da migration, foi criado um dump PostgreSQL custom temporário de 226.364 bytes, modo `0600`. `pg_restore --list` passou pelo container PostgreSQL; o arquivo foi removido depois dos health checks e sua ausência foi confirmada. Uma primeira tentativa de gerar o dump com aspas SSH incorretas falhou antes de alterar banco ou serviços. Na inspeção do checkout, encontrei um arquivo não rastreado chamado `\;`, regular, vazio e modo `0600`; confirmei o caminho e o tamanho antes de removê-lo. Não houve alteração de dados financeiros durante a publicação.

### Estado final das ações de confirmação no chat — publicado em 26/10/2026

O PR [#61](https://github.com/vitokkkj/finance-ai/pull/61) foi mesclado no commit `5791a278be970eda6a51002db983451ee416d6b9`. API/PostgreSQL, Frontend com E2E integrado e imagens/configuração pública passaram no workflow [40378907232](https://github.com/vitokkkj/finance-ai/actions/runs/40378907232). As duas primeiras tentativas ficaram mais de 11 minutos no passo de instalar Chromium com `--with-deps` e foram canceladas. O workflow passou a instalar somente o navegador (`npx playwright install chromium`); na tentativa seguinte os E2Es e todos os demais checks passaram.

O detalhe da conversa agora lê o estado atual do `AIToolCall` e apresenta esse estado no cartão original. Ações concluídas, canceladas ou falhas deixam de mostrar **Confirmar** e **Cancelar**, e a mensagem antiga de revisão é substituída por um aviso de que a ação já foi processada. A correção cobre também conversas reabertas. O resumo financeiro e o resultado final permanecem no histórico; não houve mudança no schema nem nos dados financeiros.

As verificações locais passaram: teste focado da API, E2E da compra parcelada, mypy, Ruff, lint e typecheck do frontend, e build de produção. O lint do Biome ainda aponta quatro avisos preexistentes de `!important` em `editorial-design.css`.

A VM `/opt/sophia-test` avançou em fast-forward de `9a4d972` para `5791a27`, com checkout limpo. `docker compose -f docker-compose.yml -f docker-compose.vm.yml config -q` e `up -d --build --wait` passaram. Os seis serviços estão ativos; API, web e PostgreSQL estão saudáveis. Alembic permaneceu em `0023_card_purchase_installments (head)`; não houve migration nem dump/backup porque a publicação só altera código e não modifica dados. `/`, `/api/health/live` e `/api/health/ready` retornaram `200`; `/api/accounts` sem sessão retornou `401`; `/api/docs` retornou `404`.
