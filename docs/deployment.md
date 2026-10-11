# Implantação e operação

## Topologia pública

A VM publica a aplicação por um túnel de saída da Cloudflare. `cloudflared`, Caddy e Next.js compartilham a rede Docker `edge`; o túnel encaminha `finance.ruralflow.com.br` para `http://caddy:80`. O TLS público termina na Cloudflare. Caddy recebe HTTP apenas dentro da rede privada do Compose, define cabeçalhos de segurança e encaminha para o frontend. Nenhum serviço publica porta no host.

Na zona Cloudflare, mantenha ativa a regra de redirecionamento 301 `http://finance.ruralflow.com.br/*` → `https://finance.ruralflow.com.br/${1}`, preservando a query string. Ela vale somente para SophIA. Não habilite a opção global “Always Use HTTPS” da zona se isso também alterar o site principal ou outros subdomínios.

Next.js encaminha `/api/*` para FastAPI. API e worker acessam PostgreSQL pela rede `data`, marcada como interna; a API também participa da rede `app`. O worker e o banco não têm interface na rede pública. O túnel não alcança diretamente a API nem o banco.

Na implantação, Next.js recebe `API_INTERNAL_URL=http://api:8000` durante o build para que o proxy de `/api/*` alcance a API pela rede Docker. API, web, worker, Caddy e `cloudflared` usam sistema de arquivos raiz somente leitura e `/tmp` temporário. O worker não recebe o segredo TOTP do proprietário.

A API roda com um único worker para manter o limitador de tentativas de login consistente. A validação de senha e a etapa de MFA compartilham o mesmo orçamento de tentativas por conta e origem. Bloqueios ativos não são expulsos por novas origens: se a tabela de chaves atingir a capacidade configurada, novas chaves recebem 429 até que entradas expirem. Esta instalação foi projetada para uma instância de API; não escale réplicas sem antes mover o limitador para um mecanismo compartilhado.

Fotos de perfil aceitam JPEG, PNG ou WebP até 8 MB no navegador. A API decodifica e valida o conteúdo, limita a imagem a 8 megapixels, normaliza orientação e dimensões para no máximo 512 px e armazena WebP associado ao usuário. A leitura exige uma sessão autenticada e envia `Cache-Control: no-store`; a migration `0013_profile_avatar` só acrescenta os campos opcionais do perfil.

O repositório público está em [vitokkkj/finance-ai](https://github.com/vitokkkj/finance-ai), sob licença MIT. Endereços privados da VM, arquivos `.env`, tokens de túnel, credenciais OAuth e dados financeiros não pertencem ao GitHub.

## Requisitos

- Docker Compose V2 `2.24.4` ou superior, por causa de `!reset` e `!override` usados para remover portas e mounts de desenvolvimento.
- Zona `ruralflow.com.br` gerenciada pela Cloudflare e um túnel dedicado chamado `finance-sophia`. Não reutilize um túnel que publique outros domínios.
- Conectividade de saída da VM para a Cloudflare na porta `7844` (UDP ou TCP). Não é necessário abrir portas de entrada para a internet.
- Token do túnel salvo em arquivo local privado no servidor. `cloudflared` executa como usuário não-root e lê `/run/secrets/cloudflare_tunnel_token`; o token não é colocado na linha de comando, no `.env` nem no Git.
- Segredo TOTP do proprietário em `OWNER_TOTP_SECRET`, no `.env` privado da VM. Gere-o em um terminal confiável com `python3 scripts/generate-owner-totp.py` e mantenha a chave fora do banco e do repositório. O QR de pareamento do Authy é exibido pela aplicação após a autenticação da senha e autorização temporária do servidor.
- Token aleatório de primeiro pareamento em `MFA_ENROLLMENT_TOKEN`. Gere com `openssl rand -hex 32`, informe-o somente na tela privada de configuração do Authy e apague a variável do `.env` depois de confirmar o primeiro código. A tela não revela o QR sem esse token e a senha da conta.
- Token aleatório e temporário para criar a primeira conta. Gere com `openssl rand -hex 32` e configure em `INITIAL_SETUP_TOKEN` somente durante o bootstrap.
- O limitador combina endereço de origem e conta, mas fica em memória e reinicia junto com a API. Configure também rate limiting da Cloudflare para os endpoints de autenticação, especialmente login, bootstrap e pareamento MFA.
- `POSTGRES_PASSWORD` aleatória, com letras e números para evitar codificação especial na URL do banco.

Não reutilize valores de desenvolvimento do `.env.example` em produção. Não cole tokens, senhas, códigos TOTP, cookies ou credenciais OAuth no chat, em issues, logs ou workflows.

## Rota Cloudflare

No túnel dedicado `finance-sophia`, a rota publicada deve usar:

- Hostname público: `finance.ruralflow.com.br`
- Serviço interno: `http://caddy:80`
- Catch-all: `http_status:404`

Ao salvar a rota, a Cloudflare cria o DNS CNAME proxied apontando para o túnel. O conector `cloudflared` precisa estar na rede Docker `edge` deste Compose para resolver `caddy`. Não crie registros A/AAAA apontando para o IP da VM e não publique as portas 80/443 do host.

O hostname público permite que qualquer visitante alcance a tela de login. O acesso aos dados exige a conta existente, senha e TOTP; a criação inicial exige o token temporário e o TOTP do proprietário. A rota pública não substitui a autenticação da aplicação.

## Preparar a VM e publicar

1. No `.env` privado da VM, defina `APP_DOMAIN=finance.ruralflow.com.br`, `OWNER_TOTP_SECRET`, credenciais PostgreSQL e `CLOUDFLARE_TUNNEL_TOKEN_FILE=./secrets/cloudflare-tunnel-token`. Configure `INITIAL_SETUP_TOKEN` somente se ainda não houver uma conta; remova-o depois do bootstrap. Para o primeiro pareamento do autenticador, configure temporariamente `MFA_ENROLLMENT_TOKEN` com um valor aleatório de pelo menos 32 caracteres.
2. Crie o diretório `secrets` como `root` com permissão `0700` e o arquivo `cloudflare-tunnel-token` como `root:root`, permissão `0644`. A pasta não é rastreada pelo Git e impede leitura por usuários locais sem privilégio; o arquivo precisa ser legível pelo processo não-root do container `cloudflared`.
3. Crie o túnel dedicado `finance-sophia` no painel Cloudflare e instale o token desse conector diretamente no arquivo secreto da VM por um canal administrativo confiável; não o envie pelo chat nem o grave em histórico de shell. Não publique a rota ainda. Não reutilize o túnel `ruralflow-vm`, que já publica `ruralflow.com.br` para outro serviço.
4. Valide a configuração sem imprimir valores interpolados: `docker compose -f docker-compose.yml -f docker-compose.vm.yml config -q`.
5. Inicie os serviços: `docker compose -f docker-compose.yml -f docker-compose.vm.yml up -d --build`. Confirme que os seis serviços estão em execução e que o Compose não publica portas no host.
6. Só depois da validação interna, publique no túnel dedicado a rota `finance.ruralflow.com.br` → `http://caddy:80`, com fallback `http_status:404`.
7. Confirme que o conector `cloudflared` está conectado no painel e acesse `https://finance.ruralflow.com.br`. Verifique os cabeçalhos HSTS, proteção contra framing, MIME sniffing e permissões do navegador. Cookies usam o prefixo `__Host-`, `Secure`, `HttpOnly`, `SameSite=Strict` e validade máxima de 24 horas. A conta existente exige novo login com senha e TOTP; a migration `0011_public_auth_hardening` invalida sessões antigas, mas preserva os dados financeiros.
8. No primeiro login, informe e-mail e senha; a aplicação então solicita o MFA. Para parear o Authy, escolha **Configurar autenticador**, informe o token temporário, escaneie o QR e confirme o código atual do Authy. O QR vale por dez minutos. Depois da confirmação, remova `MFA_ENROLLMENT_TOKEN` do `.env` e recrie a API; o acesso continuará exigindo senha e TOTP.

A migration `0011_public_auth_hardening` revoga sessões antigas para exigir novo login. A migration `0012_owner_mfa_enrollment` adiciona apenas o estado e o prazo temporário de pareamento; nenhuma delas remove dados financeiros.

## Verificação de segurança pós-deploy

- `docker compose -f docker-compose.yml -f docker-compose.vm.yml ps`: confira que web, API, worker, PostgreSQL, Caddy e cloudflared estão ativos.
- Verifique que o Compose de produção não publica portas no host: `docker compose -f docker-compose.yml -f docker-compose.vm.yml port web 3000`, `port api 8000`, `port postgres 5432` e `port caddy 80` não devem retornar um endereço público.
- Acesse `/api/health/live` e `/api/health/ready` pelo hostname HTTPS; confirme redirecionamento HTTP→HTTPS e cabeçalhos de segurança.
- Uma chamada sem sessão a `/api/accounts` deve retornar `401`; `/api/docs` deve retornar `404` em produção. Com o proprietário já criado, `requires_setup` em `/api/auth/setup-state` deve ser `false`.
- Confirme que a rota de bootstrap está indisponível depois que a conta do proprietário existir e que um login inválido não cria sessão.
- Confira `alembic current`, integridade dos saldos no Finance Engine e logs sem segredos. Os backups e a recuperação permanecem sob responsabilidade do Proxmox, fora deste repositório.

Não teste login real, não crie usuários adicionais e não use dados financeiros de produção em verificações automatizadas.

## Desenvolvimento local

O arquivo `.env.example` e `docker compose up` são para desenvolvimento em `http://localhost:3000`. O frontend fica ligado a `127.0.0.1`; o cookie `Secure` é desligado para HTTP local e o TOTP pode ficar sem configuração. API e PostgreSQL continuam sem portas publicadas. Não use esse modo para exposição pública.

## Integração com o plano ChatGPT

O OAuth para a VM é concluído no computador que tem o navegador. Depois, as credenciais protegidas são transferidas por SSH e a VM renova os tokens. O host da VM precisa manter seu identificador estável. Consulte o fluxo oficial de [Sign in with ChatGPT para VMs auto-hospedadas](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms). Tokens ficam em volume privado montado somente na API, com permissões restritas. Não configure fallback para chamadas pagas de API.

## Dados e recuperação

Os backups da VM são gerenciados pelo Proxmox fora deste repositório. Os snapshots não devem ser tratados como teste de restauração: mantenha uma verificação de recuperação conforme a política privada do proprietário. Backups podem conter dados financeiros; não os envie ao GitHub, logs, tickets ou serviços sem autorização.

Antes de uma migration ou atualização que possa afetar dados, valide a recuperação conforme o procedimento do Proxmox e confira a revisão corrente:

```bash
docker compose -f docker-compose.yml -f docker-compose.vm.yml exec api alembic current
docker compose -f docker-compose.yml -f docker-compose.vm.yml exec api alembic upgrade head
```

Depois da atualização, confira `/api/health/live`, `/api/health/ready`, login e o Finance Engine. Preserve a imagem anterior até confirmar a operação; não reverta migrations destrutivas automaticamente.

## Comandos de operação

```bash
docker compose -f docker-compose.yml -f docker-compose.vm.yml ps
docker compose -f docker-compose.yml -f docker-compose.vm.yml logs --tail=100 cloudflared caddy web api worker postgres
docker compose -f docker-compose.yml -f docker-compose.vm.yml exec api alembic current
```

Os logs não devem conter senhas, token do túnel, token de bootstrap, códigos TOTP, cookies ou credenciais OAuth. Remova o token de primeiro acesso do `.env` assim que a conta for criada.
