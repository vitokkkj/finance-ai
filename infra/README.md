# Infraestrutura

A execução local está descrita no `docker-compose.yml` da raiz. A VM Debian executa um ambiente privado de testes; o web fica vinculado ao IP Tailscale e é acessível diretamente pelo tailnet. API e PostgreSQL permanecem na rede interna do Compose, sem portas publicadas. A publicação de produção em `sophia.matheus.inf.br` por Cloudflare Tunnel ainda não está configurada. Consulte [docs/deployment.md](../docs/deployment.md) para o estado e as restrições.
