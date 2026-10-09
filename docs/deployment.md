# Implantação planejada

Este documento registra a topologia de produção planejada e o ambiente de testes atual. O domínio disponível é `matheus.inf.br`, e o subdomínio planejado para a aplicação é `sophia.matheus.inf.br`. A VM de teste já executa a SophIA via Docker Compose; **DNS, Cloudflare Tunnel e publicação de produção ainda não foram configurados.** O ambiente de desenvolvimento local continua sendo iniciado por `docker compose up`.

## Topologia

```text
Internet
   ↓
sophia.matheus.inf.br
   ↓
Cloudflare (DNS e HTTPS)
   ↓
Cloudflare Tunnel
   ↓
VM Debian (administração por SSH)
   ↓
Docker Compose
   ├── web
   ├── api
   ├── worker
   └── postgres
```

O túnel será iniciado de dentro da VM e encaminhará somente para o serviço web. Não se planeja abrir portas de entrada no roteador ou publicar diretamente a API.

## Ambiente de testes atual

- Debian 13 na VM, com Docker Engine e plugin Docker Compose instalados pelo repositório oficial.
- O ambiente de teste usa um projeto Docker Compose e um volume PostgreSQL dedicados. Nenhum dado financeiro local foi copiado.
- A migration aplicada está em `0009_optional_opening_balance` (`head`). API, web e PostgreSQL passam seus health checks; o worker está em execução.
- O web escuta em `IP-TAILSCALE-DA-VM:80`, endereço da interface Tailscale da VM. Acesse diretamente `http://IP-TAILSCALE-DA-VM` com o Tailscale ativo no dispositivo. Não é necessário abrir um túnel SSH.
- `WEB_ALLOWED_DEV_ORIGINS=IP-TAILSCALE-DA-VM` autoriza o Next.js em modo desenvolvimento a servir os recursos de desenvolvimento para esse hostname Tailscale; a lista é configurável por ambiente.
- A porta 80 é vinculada especificamente ao IP Tailscale; não fica publicada no IP da interface LAN da VM. API e PostgreSQL não publicam portas; o banco fica na rede interna do Compose.
- O `.env` de teste fica somente na VM, com permissão `0600`, e não contém chave de API. A autorização OAuth do ChatGPT fica em volume privado montado somente na API; tokens não são enviados ao frontend nem ao worker. A conexão OAuth real ainda depende da autorização do proprietário no navegador e do fluxo open source documentado.
- Esta implantação continua em modo de desenvolvimento (Next.js dev server e API com reload) e deve receber somente dados de teste. Antes de usar dados reais, preparar imagens de produção, sessão com cookie `Secure` atrás de HTTPS, backups e teste de restauração, monitoramento e plano de atualização/rollback.
- Os backups ficarão sob responsabilidade do proprietário da VM, por snapshots diários da VM Debian no Proxmox, com retenção planejada de 30 dias. A aplicação não criará uma rotina própria de backup. Antes de usar dados reais, validar a restauração de um snapshot e criar um snapshot adicional antes de migrations ou atualizações de risco.

O endereço de teste não é público e não usa `sophia.matheus.inf.br`; o acesso depende do dispositivo estar conectado ao tailnet. O tráfego de teste usa HTTP na interface Tailscale. A publicação futura pelo domínio usará HTTPS via Cloudflare Tunnel.

## Limites de segurança

- PostgreSQL permanece na rede interna do Compose, sem porta publicada no host ou acesso pela internet.
- O acesso ao domínio usa HTTPS. A autenticação privada da SophIA continua obrigatória.
- Cloudflare Access será exigido para o acesso externo e funcionará antes do login da SophIA; não substitui a autenticação da aplicação.
- Chaves, tokens e senhas ficam em variáveis de ambiente ou em mecanismo local de secrets na VM; arquivos `.env` não entram no Git.
- Chaves de provedor, cookies de sessão e outros segredos nunca são enviados ao frontend.
- A criação inicial da conta permanece controlada pela aplicação; não haverá cadastro público.
- A VM é administrada por SSH. A configuração de firewall, atualizações e procedimento de recuperação serão validados durante a etapa de produção; os snapshots diários no Proxmox são responsabilidade do proprietário.

## Preparação antes da publicação

Antes de apontar `sophia.matheus.inf.br` para a VM, validar autenticação e recuperação de acesso, restauração de um snapshot do Proxmox, atualização e rollback de imagens, rotação de secrets, logs sem dados sensíveis e health checks. Cloudflare Access ficará ativo antes do login da aplicação, com acesso restrito à identidade autorizada.
