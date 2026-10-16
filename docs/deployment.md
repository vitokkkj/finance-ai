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
