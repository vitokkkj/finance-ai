# Integrações — plano futuro

Nenhuma integração externa é chamada na Fase 1.

## Open Finance

A integração planejada é Pluggy/MeuPluggy, inicialmente somente leitura para as próprias contas. A implementação consultará a documentação oficial atual antes de definir endpoints ou formatos. Senhas bancárias não serão armazenadas. DTOs de integração e idempotência serão definidos junto com a fase de sincronização.

## ChatGPT Plus (Sign in with ChatGPT)

O provider preparado para a SophIA usa OAuth da conta ChatGPT do proprietário, sem API key e sem cobrança de API. O fluxo oficial atende aplicativos open source hospedados pelo próprio usuário, inclusive em VM remota: o código é publicado sob uma licença escolhida, o usuário autoriza pelo navegador e as credenciais protegidas são transferidas por SSH para um volume privado acessível somente pela API. A conexão real ainda não foi autorizada. A franquia é compartilhada com o uso do ChatGPT/Codex, sujeita aos limites da conta e do aplicativo; isso não compartilha histórico ou memórias do ChatGPT com a SophIA. Não há fallback automático para API paga. Consulte [Sign in with ChatGPT](https://developers.openai.com/siwc/token-sharing-open-source) e [self-hosted VMs](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms).

## Implantação

O alvo de publicação planejado é `sophia.matheus.inf.br`, com DNS no Cloudflare e tráfego encaminhado por Cloudflare Tunnel a uma VM Debian acessada por SSH. HTTPS será mantido, PostgreSQL permanecerá privado sem portas publicadas, e a autenticação da SophIA continuará obrigatória; Cloudflare Access poderá ser acrescentado como proteção adicional. O deploy ainda não está implementado. Consulte [deployment.md](deployment.md) para os limites e a topologia planejada.
