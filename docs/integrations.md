# Integrações

## Sign in with ChatGPT

A SophIA usa OAuth Sign in with ChatGPT para enviar pedidos elegíveis à Responses API com autorização do plano ChatGPT. O fluxo não usa uma chave da API nem precisa de `OPENAI_API_KEY`, segredo de cliente ou fallback pago. O código público está no [repositório finance-ai](https://github.com/vitokkkj/finance-ai), sob MIT.

O uso não compartilha o histórico ou as memórias do ChatGPT com a SophIA. Em contas Plus, o limite de cinco horas é compartilhado entre os aplicativos que usam o plano; a SophIA não recebe uma franquia separada. A pessoa pode consultar e limitar o uso por aplicativo em ChatGPT → Configurações → Uso. As condições de elegibilidade e os modelos permitidos dependem da conta e do consentimento atual.

Na VM auto-hospedada, o navegador usado para concluir OAuth precisa estar no computador local. A credencial protegida é então transferida à VM por canal seguro; a VM mantém um `ext_agent_host_id` persistente e atualiza seus tokens. O frontend e o worker não recebem tokens. Se a sessão for revogada ou expirar sem renovação, a integração para com uma mensagem de erro e não muda para chamadas pagas.

Referências oficiais:

- [Visão geral de Sign in with ChatGPT e uso do plano](https://developers.openai.com/siwc/token-sharing-open-source)
- [Procedimento oficial para VMs auto-hospedadas](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)
- [Contas, sessões, limites e segurança de credenciais](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)

## Open Finance

Pluggy/MeuPluggy permanece uma candidata futura, não uma integração implementada. Antes de começar, consulte a documentação oficial atual, defina escopos de leitura, idempotência e reconciliação, e minimize os dados enviados. A SophIA nunca armazena senhas bancárias nem inicia pagamentos.

## Implantação

A instância permanece privada e auto-hospedada. O repositório público documenta a arquitetura sem publicar endereço de VM, domínio privado, tokens ou dados financeiros. Consulte [deployment.md](deployment.md) para procedimentos e requisitos de operação.
