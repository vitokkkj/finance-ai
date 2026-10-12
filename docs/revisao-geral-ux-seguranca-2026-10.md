# Revisão geral da SophIA — outubro de 2026

## Escopo

Esta revisão cobre a API, regras financeiras, frontend, segurança e operação da SophIA, além dos fluxos de avisos, compromissos, cartões e imagens analisadas pela IA. O painel da zona `ruralflow.com.br` foi conferido diretamente no navegador do Codex em 11/10/2026. O túnel de `finance.ruralflow.com.br` aparece como CNAME com proxy Cloudflare ativado e aponta para `finance-sophia`; o registro não expõe um IP de origem no DNS exibido.

## Prioridades tratadas

### Segurança e backend

- **Limite global de requisições:** a API agora limita corpos `/api/*` a 16 MiB, inclusive quando enviados em blocos sem `Content-Length`; o Caddy também impõe o mesmo teto. O endpoint de imagens preserva limite próprio mais restrito.
- **Replay de TOTP:** um contador TOTP já usado não pode autenticar outra vez. A última janela aceita fica gravada por usuário e é consumida por atualização atômica. A migration `0016_totp_replay` adiciona uma coluna nullable sem alterar lançamentos.
- **Cabeçalhos de proxy:** Uvicorn deixou de confiar em toda a rede privada para `X-Forwarded-*`. A conexão pública continua terminando no Cloudflare e Caddy; o backend não aceita cabeçalhos de proxy de serviços internos como identidade do cliente.
- **Arquivamento de contas:** a API calcula o saldo atual pelo Finance Engine e bloqueia arquivamento quando o saldo é diferente de zero ou não pode ser determinado. O frontend explica o saldo e orienta a zerar ou conciliar a conta.
- **Foto de perfil:** o limite real agora é 48 megapixels, alinhado à interface e à documentação; a imagem é normalizada para 512×512.
- **Previsão e avisos:** a janela de sete dias atravessa a virada do mês; avisos abrem o compromisso, recorrência ou fatura exatos, com destaque e foco. Pagamentos permanecem sujeitos à confirmação do usuário.
- **Visão de faturas:** a página de cartões ganha uma lista consolidada de todas as faturas em aberto, ordenada pelo vencimento mais próximo e com atalho para detalhes/pagamento. Os ciclos selecionados por cartão também ficam em ordem crescente de vencimento; valores são derivados pelo Finance Engine e o endpoint respeita `users.id` da sessão. Faturas futuras só aparecem quando já há saldo ou compras registradas para o ciclo.
- **Cartões e ciclo futuro:** a regra de saldo inicial importado de fatura futura está documentada: compras/parcelas assumidas reduzem o limite disponível; intenção de compra ainda não realizada não deve ser lançada como fatura.

### Frontend e uso móvel

- O menu móvel usa o mesmo breakpoint responsivo, pode abrir por gesto iniciado na borda esquerda e fechar com gesto, backdrop ou `Escape`.
- O drawer tem isolamento do conteúdo de fundo, foco inicial e restauração de foco, atributos ARIA e bloqueio de rolagem do documento enquanto está aberto.
- A navegação lateral permanece rolável em telas baixas; áreas de toque do controle foram ampliadas.
- O breakpoint visual foi unificado em 760 px para alinhar a mudança de layout e o modo drawer.
- A lateral reserva uma faixa fixa para a conta e a saída, e usa o espaço restante para mostrar e rolar várias conversas; em telas baixas, a própria lateral também pode rolar sem esconder esses controles. “Nova conversa” ficou compacta. No celular, “Atualizar aplicativo” recarrega os dados do app e restaura a conversa ou seção aberta; aparece um aviso antes de descartar rascunho e o botão fica desativado durante uma resposta.
- No celular, Enter quebra linha e o botão de envio envia a mensagem; no computador, Enter continua enviando e Shift+Enter quebra linha. Campos de texto, datas e listas usam fonte mínima de 16 px para evitar o zoom automático do Safari ao focá-los, mantendo o zoom por gesto disponível.
- O seletor do resumo foi exercitado no navegador: ao escolher outro mês, fluxo e categorias são atualizados; o rótulo agora informa “Mês analisado”. A previsão “A pagar” continua mostrando o mês corrente, conforme sua função de compromissos próximos.
- Categorias exibem **Receitas** antes de **Despesas**.
- O tratamento de imagens do chat aceita até quatro anexos e encaminha o tipo WebP verdadeiro depois da normalização.
- No celular, o contexto financeiro inicia fechado e só abre pelo controle solicitado; o contador de avisos fica sobreposto ao sino, sem deslocá-lo; e o resumo mensal usa linhas de rótulo/valor para evitar colisões em larguras estreitas.

## Riscos e melhorias que permanecem

| Prioridade | Item | Estado e próxima ação |
|---|---|---|
| P1 operacional | Rate limits e WAF no Cloudflare | Painel revisado: a zona está no plano Free, não há regras personalizadas nem regra de rate limiting configurada. Browser Integrity Check está ligado; Bot Fight Mode e Under Attack estão desligados; a proteção HTTP DDoS padrão aparece ativa. Não foram feitas mudanças no painel. Criar limites específicos para login, bootstrap e MFA segue como ação recomendada. |
| P1 operacional | Firewall e SSH da VM | A conexão SSH de deploy foi validada; política de firewall, restrição de origem e autenticação por senha precisam de revisão administrativa própria. A chave root permanece instalada conforme decisão do usuário. |
| P2 segurança | CSP com `unsafe-inline` | Permanece para compatibilidade com Next.js. Avaliar nonce/hash em ambiente de produção e remover a exceção apenas após validar hidratação, fontes e navegação. Não há XSS confirmado nesta revisão. |
| P2 produto | Notificações do sistema | Os avisos são internos enquanto o site está aberto. Push no iPhone requer service worker, inscrição iniciada por ação explícita e configuração de push; manter opt-in e links diretos para o item. |
| P2 qualidade | Automação do navegador | Não há suíte de testes E2E/visual no projeto. Adicionar fluxos para login/MFA, compromissos e baixa, fatura parcial/total, virada do mês, upload múltiplo, tema e drawer móvel. |
| P2 UX | Verificação visual em telas reais | A CUA confirmou o app aberto no navegador desktop e os defeitos mobile foram reproduzidos pelas capturas fornecidas. O executor CUA disponível não oferece controle de viewport; a checagem em iPhone físico e larguras automatizadas continua pendente. |
| P2 operação | Histórico completo de ocorrências | O item indicado pelo aviso pode ser aberto por ID mesmo fora da faixa recente. A navegação geral do histórico ainda precisa de paginação/faixas de data. |

Pontos fortes confirmados no código: não há cadastro público; o bootstrap inicial é protegido por token; senhas usam Argon2; sessões persistem apenas hashes aleatórios; cookie de sessão é `HttpOnly`, `Secure` e `SameSite=Strict`; operações financeiras usam a sessão autenticada e filtram por `users.id`; PostgreSQL não publica porta; imagens do chat não são persistidas no histórico. Isso não substitui auditoria das regras operacionais do Cloudflare e do host.

## Avisos de vencimento

Atualmente, os avisos atualizam ao abrir o app, ao voltar para a aba e periodicamente enquanto ele está aberto. Eles apontam para o registro que exige atenção e permitem marcar como pago/recebido depois da conferência. Ainda não há alerta do sistema, e-mail ou push com o app fechado.

As referências consultadas mostram padrões úteis: [Organizze — alertas de contas vencendo ou atrasadas](https://ajuda.organizze.com.br/hc/pt-br/articles/360035805714-Android-Vis%C3%A3o-geral-Alertas) leva às contas que podem ser baixadas; [Mobills — personalizar a tela inicial](https://mobills.zendesk.com/hc/pt-br/articles/360051434294-Como-personalizar-a-tela-inicial-do-meu-Mobills) apresenta pendências e alertas. Para push em iOS, a [documentação do WebKit](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/) exige um web app na Tela de Início, permissão iniciada pelo usuário e assinatura push.

## Validação local

| Verificação | Resultado |
|---|---|
| API — testes | **158 passaram; 2 ignorados** porque dependem de permissões POSIX indisponíveis no Windows. |
| Ruff | Passou. |
| Mypy | Passou: 28 arquivos. |
| Biome lint | Passou com quatro avisos existentes sobre `!important` na regra `prefers-reduced-motion`. |
| TypeScript | Passou. |
| Build Next.js | Passou; rotas estáticas geradas. |
| Caddyfile 2.11.6 | Configuração validada no ambiente da VM. |
| Compose da VM | Configuração validada sem imprimir valores interpolados. |
| Deploy e migration | A revisão `16110c9` foi publicada; API e web saudáveis; Alembic em `0016_totp_replay`; PostgreSQL sem porta publicada no host. O novo Caddyfile foi validado e recarregado. O ajuste complementar para telas baixas ainda aguarda publicação. |
| HTTP público | `/api/health/live` e `/api/health/ready` retornam 200; `/api/accounts` sem sessão retorna 401; `/api/docs` retorna 404; HTTP redireciona para HTTPS. HSTS, CSP, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, Referrer-Policy e Permissions-Policy foram observados. |
| Painel Cloudflare | Conferido: Full TLS com modo automático; Browser Integrity Check ligado; regras customizadas e rate limiting ausentes; tunnel DNS do subdomínio está proxied. |

## Próximos passos

1. Criar regras de rate limiting para login, bootstrap e MFA, com limites definidos para o padrão real de uso e sem bloquear o usuário legítimo.
2. Fazer validação visual e de gestos em iPhone e larguras móveis; a CUA desta sessão não expõe seleção de viewport.
3. Planejar push opt-in e automação E2E sem armazenar conversas financeiras em cache.
