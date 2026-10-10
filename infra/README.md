# Infraestrutura

A execução local está descrita no `docker-compose.yml` da raiz. Uma instância auto-hospedada de teste pode usar `docker-compose.vm.yml` para iniciar o frontend e a API em modo de runtime.

Mantenha hostnames, IPs, chaves SSH, `.env`, credenciais OAuth, dumps e dados financeiros fora deste repositório público. API e PostgreSQL ficam na rede interna do Compose; somente o frontend deve receber tráfego do navegador.

O Compose não configura backups. Valide o procedimento de cópia e restauração na plataforma do host antes de depender dos dados. Consulte [docs/deployment.md](../docs/deployment.md) para checklist de deploy, segurança e recuperação.
