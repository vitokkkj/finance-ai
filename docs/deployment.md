# Implantação e operação

## Topologia

O projeto separa frontend, API, worker e PostgreSQL em serviços Docker Compose. Em produção, somente o frontend deve receber tráfego externo; API e banco ficam em redes internas. O PostgreSQL não publica porta no host. Credenciais de OAuth ficam em um volume privado montado apenas na API.

O código aberto fica no [repositório GitHub](https://github.com/vitokkkj/finance-ai), sob licença MIT. Endereços privados, domínios de teste, credenciais, arquivos `.env` e dados financeiros não pertencem à documentação pública nem ao repositório.

## Desenvolvimento e VM privada

- Desenvolvimento local: `docker compose up`.
- Runtime para uma VM privada: `docker compose -f docker-compose.yml -f docker-compose.vm.yml up -d --build`.
- A VM é um ambiente auto-hospedado privado. Registre hostnames, IPs e detalhes da rede somente no inventário operacional privado do proprietário.
- A configuração de runtime inicia o frontend com o servidor Next.js de produção e a API sem autoreload. API e PostgreSQL permanecem na rede interna do Compose.
- O arquivo `.env` é exclusivo do ambiente e não entra no Git. `OPENAI_API_KEY` não é necessário no fluxo Sign in with ChatGPT. Os tokens OAuth ficam no volume privado da API, com permissões restritas.
- A situação atual da autorização deve ser consultada em Preferências ou em `GET /api/ai/status`; não deduza que uma cópia do repositório tem credenciais configuradas.

O OAuth para uma VM é concluído no computador que tem o navegador. Depois, as credenciais protegidas são transferidas por SSH e a própria VM renova os tokens. O host da VM precisa manter o seu identificador estável. Consulte o fluxo oficial de [Sign in with ChatGPT para VMs auto-hospedadas](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms).

## Dados e recuperação

O Compose não agenda nem executa backups do PostgreSQL. Este repositório não comprova a existência de snapshots, retenção ou restauração testada na plataforma que hospeda a VM; configure e valide esses itens antes de tratar o ambiente como protegido. Não considere um deploy bem-sucedido como prova de backup.

Antes de uma migration ou atualização que possa afetar dados:

1. Confira o estado do banco e a revisão atual com `docker compose exec api alembic current`.
2. Faça um backup do PostgreSQL para armazenamento privado, fora do volume em uso.
3. Valide que o arquivo existe, tem acesso restrito e pode ser restaurado em uma instância descartável.
4. Atualize os serviços e verifique `/api/health/live`, `/api/health/ready`, migrations e login.
5. Preserve o backup e a imagem anterior até confirmar a operação; tenha um procedimento de retorno que não reverta migrations destrutivas automaticamente.

Os backups podem conter informações financeiras pessoais: não os envie para o GitHub, logs, tickets ou serviços sem autorização.

## Antes de disponibilizar para acesso externo

- Use HTTPS e cookie de sessão `Secure`.
- Mantenha o cadastro público desabilitado; a criação inicial da conta é controlada pela aplicação.
- Restrinja a rede ao frontend e mantenha API/PostgreSQL sem portas públicas.
- Valide login, recuperação de acesso, limite de tentativas, logs sem segredos, health checks, backup e restauração.
- Confirme que o provedor OAuth está conectado e que o usuário autorizou o uso do plano ChatGPT. Não configure fallback para API paga sem decisão explícita.
- Faça a atualização primeiro em uma cópia de teste do banco e confira os efeitos financeiros no Finance Engine.

## Comandos de operação

```bash
docker compose -f docker-compose.yml -f docker-compose.vm.yml ps
docker compose -f docker-compose.yml -f docker-compose.vm.yml logs --tail=100 web api worker postgres
docker compose -f docker-compose.yml -f docker-compose.vm.yml exec api alembic current
docker compose -f docker-compose.yml -f docker-compose.vm.yml exec api alembic upgrade head
```
