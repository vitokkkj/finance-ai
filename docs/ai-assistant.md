# Assistente financeiro

## Escopo

O assistente é a entrada principal da aplicação. Ele mantém conversas privadas e pode consultar ou registrar operações financeiras pela API. O chat pode agendar novos compromissos recorrentes com prévia e confirmação; consulta, edição, cancelamento e marcação de pagamento continuam disponíveis na área financeira existente. Integração Pluggy, previsões, embeddings, agentes, Telegram, notificações push e outros provedores de mensagem permanecem fora do escopo atual.

O provider padrão usa OAuth Sign in with ChatGPT e chamadas a ferramentas validadas pela API. O histórico próprio da SophIA fica no PostgreSQL; o OAuth não dá acesso às conversas ou memórias do ChatGPT. O adapter fica em `apps/api/app/ai_provider.py`; o armazenamento e a renovação OAuth ficam em `apps/api/app/chatgpt_plan.py`; conversas e o ciclo de chamadas ficam em `ai.py` e `ai_chat.py`; as ferramentas autorizadas estão em `ai_tools.py`. Não se usa chave da API nem há fallback para cobrança da API.

O título da primeira mensagem recebe uma sugestão curta do modelo pela mesma conexão ChatGPT quando o modelo já é necessário para responder. Essa solicitação breve usa o limite compartilhado do plano Plus e não usa uma chave da API nem gera cobrança da API. Quando o parser determinístico resolve a mensagem sem modelo, ele gera um título local. O usuário pode editar o título; a sidebar mostra nomes longos com reticências e tooltip.

## Fonte dos dados e ferramentas

O modelo não acessa SQL e não recebe `user_id`. A API injeta o usuário autenticado nas chamadas, e as ferramentas usam os comandos e consultas financeiras já existentes. As ferramentas atuais consultam:

- contas e saldos;
- lançamentos, filtros e busca;
- categorias e resumo mensal ou por categoria;
- cartões, faturas e compras da fatura;
- resumo financeiro do dashboard.
- compromissos recorrentes e ocorrências futuras.

Uma conta sem saldo inicial ou data-base conhecidos retorna `balance: null`. A SophIA deve informar que o saldo daquela conta ainda é desconhecido, sem tratá-lo como zero. Se qualquer conta ativa estiver incompleta, o saldo consolidado também não está disponível.

As ferramentas de escrita registram despesas ou receitas comuns já ocorridas, transferências próprias, compras já feitas no cartão, categorias, totais de faturas preexistentes e compromissos futuros recorrentes. Para importar faturas em lote, a SophIA usa o total informado por mês, desconta compras daquele ciclo que já estejam cadastradas e registra somente a diferença como dívida inicial. Isso evita duplicar uma compra e não cria despesas históricas. Toda importação de faturas exige confirmação explícita; o resumo mostra os meses, compras já lançadas e saldo inicial que será gravado. Transferências e compras são eventos históricos manuais; não enviam instruções ao banco. Quando uma ferramenta falha, o backend substitui o rascunho do modelo por uma resposta de erro determinística.

### Agendamentos pelo chat

`create_recurrence` atende pedidos de programar despesas/receitas que ainda não aconteceram, como “crie um gasto fixo de R$ 282 por mês, todo dia 08, de novembro de 2026 até abril de 2028”. Para um pedido completo de despesa mensal, o backend identifica valor, conta, categoria, período e vencimento e prepara essa mesma ferramenta sem depender de o modelo escolher chamá-la. Se um dado estiver ausente ou ambíguo, a mensagem vai ao modelo SMART para sugerir opções e perguntar. A SophIA transforma os meses em datas civis exatas e mostra descrição, tipo, valor, conta, categoria, frequência e primeira/última ocorrência para confirmação. “Pix” é uma forma de pagamento, não uma conta bancária; pode ser anotada no compromisso. O chat não grava a regra enquanto a pessoa não confirmar.

Depois da confirmação, a regra aparece em **Programados** e gera ocorrências previstas no horizonte do Finance Engine. Essas previsões não criam despesa nem mexem no saldo. Quando o usuário informa que pagou e marca uma ocorrência como paga, o sistema cria uma transação única na data local atual; a repetição do ato usa a mesma transação. Uma regra ativa idêntica, para mesma conta, categoria, valor, período e observação, é recusada para evitar duplicação. Se houver várias contas compatíveis, o assistente pergunta qual usar; não assume uma conta com base apenas em “Pix”.

Todos os valores usados nos dados estruturados vêm da API e do Finance Engine. O texto do modelo pode explicar esses dados, mas a UI apresenta os valores também em cartões estruturados. Valores monetários permanecem texto decimal e são formatados sem cálculos no navegador.

## Conversas, memória e privacidade

Uma mensagem pode incluir uma foto JPEG, PNG ou WebP, selecionada pelo botão de anexo ou colada no campo do chat com Ctrl+V/⌘+V. O navegador reduz a imagem para até 2.048 px e a API valida e reencoda o conteúdo; a foto só é enviada ao provedor configurado quando a mensagem é enviada, sem fallback automático. Com AI_PROVIDER=chatgpt_plan, a imagem é enviada ao ChatGPT conectado. A SophIA grava no histórico apenas uma indicação de que havia uma imagem; os bytes e metadados não são persistidos nem reutilizados nos turnos seguintes. A interface avisa sobre o envio antes da análise.

O endpoint de mensagens aceita até 20 envios por usuário a cada 60 segundos e mantém no máximo três respostas do assistente em andamento por processo da API. Respostas limitadas retornam HTTP 429 e o cabeçalho Retry-After. Esses limites reduzem abuso e pressão sobre o provider; a Cloudflare continua responsável por limitar tráfego abusivo antes de chegar à aplicação.

Em turnos com foto, as ferramentas ficam limitadas à consulta de contas, categorias, cartões e faturas, à prévia de cadastro de cartão e à prévia de importação de saldo de fatura. Se o cartão ainda não existir, `create_credit_card_with_invoices` prepara cartão e totais de faturas em uma única confirmação; a execução grava ambos juntos. Com cartão já cadastrado, `set_card_invoice_opening_balances` prepara a importação para confirmação. Nenhum desses fluxos cria compras ou despesas históricas. Se faltarem limite, dia de fechamento ou vencimento, a SophIA repete os totais lidos ao pedir essa informação, para permitir continuar sem reenviar a imagem. Totais pouco legíveis ou meses ambíguos também exigem esclarecimento. O provider Ollama não recebe imagens.

As mensagens de usuário e assistente são persistidas para formar histórico e contexto; conteúdo digitado pelo usuário permanece na conversa. O contexto enviado ao provider limita-se às 24 mensagens mais recentes e a até 20 preferências explicitamente salvas. CPF, e-mail e sequências numéricas longas são ocultados no texto enviado ao provider.

Chamadas internas de ferramentas são guardadas na tabela de auditoria, com argumentos e resumos de saída sanitizados. A API da interface lista somente papéis `USER` e `ASSISTANT`. Preferências têm até 500 caracteres e podem ser criadas, editadas e removidas na tela Preferências, ou salvas no chat quando o usuário pedir explicitamente para lembrar. Não são inferidas automaticamente. Elas orientam a conversa quando relevantes, mas a mensagem atual prevalece; preferências nunca alteram lançamentos nem substituem confirmações.

Exemplos úteis: “Ao registrar despesas sem conta indicada, prefira a conta Sicredi” e “Classifique compras na Padaria Central como Alimentação”. Uma conta padrão ou cartão principal pode preencher um relato sem destino explícito somente se combinar com a forma de pagamento descrita; a SophIA informa o destino escolhido e permite que o usuário o corrija. Se não houver preferência adequada ou a forma de pagamento continuar ambígua, pergunta antes de gravar. Se uma preferência de conta, categoria ou estabelecimento não corresponder claramente aos cadastros atuais, o assistente também pergunta. Preferências são contexto auxiliar, não fatos financeiros.

## Modelos, streaming e uso do plano

AI_PROVIDER=chatgpt_plan é o padrão. AI_MODEL_FAST=gpt-6-luna atende interpretação, consultas diretas, categorização e seleção de ferramentas simples. AI_MODEL_SMART=gpt-6.1-sol fica reservado a comparações entre períodos, análises detalhadas, planejamento e explicações complexas. Os nomes permanecem configuráveis por ambiente e a lista efetivamente liberada pela conta pode ser consultada na conexão via python -m app.chatgpt_plan models.

A autenticação usa Sign in with ChatGPT para aplicativo open source: autorização dinâmica, PKCE, state, nonce, validação da assinatura/claims do ID token e escopo chatgpt.tokens.use.direct. Como a SophIA roda em uma VM, o bootstrap local abre o navegador neste computador e transfere o token à VM por SSH. A VM mantém um ext_agent_host_id estável; o arquivo de credenciais fica em volume do backend com permissões 0600. O worker e o frontend não recebem tokens. A VM renova access/refresh tokens; se a renovação terminal falhar, é necessário autorizar novamente.

O adapter chama somente POST https://api.openai.com/v1/responses, com bearer OAuth, store=false e stream=true. Não envia previous_response_id; a SophIA reconstrói o contexto com as mensagens salvas no PostgreSQL. A rota não acessa conversas ou memórias do ChatGPT. Para tool calling, as funções financeiras são passadas por additional_tools dentro do input, seguindo as limitações atuais da integração. O adapter aguarda response.completed; falhas/streams interrompidos não são tratados como sucesso. max_output_tokens não é enviado nessa rota.

Em contas ChatGPT Plus, a documentação oficial informa que o limite de cinco horas é compartilhado entre os aplicativos que usam o plano; não existe franquia separada para cada aplicativo. Esse uso não compartilha o histórico do ChatGPT com a SophIA. Não há chamada com chave da API, cobrança por token da API nem fallback automático. Uma cota esgotada pausa o assistente. Confira e limite o uso da SophIA em [ChatGPT → Configurações → Uso](https://chatgpt.com/#settings/Usage); revise também se a conta permite uso de créditos adicionais. Os tokens informados pelo provider aparecem no diagnóstico; custo USD permanece `null`, pois uso do plano não é faturado pela API. Leia a [documentação oficial de Sign in with ChatGPT](https://developers.openai.com/siwc/token-sharing-open-source) e [contas e limites](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions).

O Ollama é opcional. Para usá-lo deliberadamente, inicie com docker compose --profile local-ai up -d, selecione AI_PROVIDER=ollama e configure modelos locais. No Compose padrão o serviço não inicia, e falha do plano ChatGPT nunca ativa o Ollama automaticamente.

## Diagnóstico de desenvolvimento

`GET /api/ai/diagnostics` e o painel discreto em Preferências existem somente com `APP_ENV=development`, além de exigirem a sessão autenticada. Exibem até 30 interações recentes: horário local, identificador da conversa, modelo, ferramenta, status, duração, tokens e custo estimado. Erros são resumos seguros. Conteúdo de conversa, prompt interno, usuário, credenciais OAuth e token da sessão não são retornados. Segredos permanecem apenas no backend.

## Erros do provider

A integração do plano ChatGPT trata conexão ausente, autorização inválida/expirada, conta ou recurso não elegível, cota compartilhada esgotada, uso temporariamente indisponível, timeout, rede, resposta inválida e falha de ferramenta. Os erros são convertidos em mensagens amigáveis e códigos diagnósticos seguros; corpos livres, access/refresh tokens e detalhes internos não chegam ao usuário nem são registrados. A cota esgotada pausa o assistente sem trocar de provedor nem iniciar cobrança de API. Após uma revogação ou falha terminal de refresh, conecte novamente a conta. Falhas de ferramenta continuam substituindo qualquer texto de rascunho para que a SophIA não anuncie uma operação que não ocorreu.

## Validação histórica do Ollama na VM

Esta seção registra a validação anterior do Ollama opcional; o provider padrão agora é o plano ChatGPT. O modelo local testado foi Qwen3 1.7B Q4_K_M.

O caminho prioritário aceita pelo chat frases claras como “Gastei 87 reais em combustível na moto”, “Gastei 34 reais em alimentação” e “botei 100 de gasolina hj”. Esse primeiro conjunto é interpretado localmente por um parser determinístico, sem chamar o modelo: ele usa contas e categorias existentes da sessão, normaliza o valor com `Decimal`, e envia o lançamento à ferramenta financeira validada pela API e pelo Finance Engine. Com uma única conta ativa, ela pode ser usada sem o usuário nomeá-la; com várias contas, categoria ausente, cartão ou data ambígua, a SophIA pergunta no chat. Um lançamento igual já existente na mesma conta, categoria, data, valor e descrição também gera uma pergunta em vez de criar outro. O parser não registra correções (“na verdade”, “errei”) como uma nova despesa.

Respostas curtas a uma pergunta pendente sobre categoria são associadas ao relato original da mesma conversa. Se a categoria estiver cadastrada, a SophIA conclui o lançamento pelo parser, sem enviar esse turno ao modelo. Se não encontrar uma categoria, ela sugere um nome quando o relato permite inferi-lo com segurança e pergunta se pode criar a categoria e continuar o lançamento. A resposta “Sim” confirma essa sugestão; um pedido explícito como “Crie a categoria Combustível” também autoriza a criação. Sem essa confirmação, nem a categoria nem o lançamento são criados. A categoria é reutilizada se já existir, evitando duplicatas. Esse estado fica no histórico da conversa, sem tabela ou entidade financeira adicional, e também permite continuar conversas que já estavam aguardando uma categoria.

Um pedido completo de despesa fixa mensal também é interpretado por regras determinísticas quando informa categoria, valor, conta resolvida, frequência, data inicial e vencimento; o parser aceita mês/ano como `11/26` e `04/28`. Se a mensagem pedir explicitamente uma nova categoria, essa categoria é criada e a programação continua para a prévia. A ferramenta `create_recurrence` exige confirmação antes de criar a regra; nenhuma despesa ou ocorrência paga é criada nesse passo. Se faltar um campo ou houver mais de uma conta, o pedido segue ao modelo SMART para sugestão e esclarecimento.

O modelo local segue disponível para perguntas abertas e consultas que ainda dependem de tool calling. Nessa parte, a validação não passou: o Qwen 1.7B excedeu 300 segundos com 19 ferramentas; com três ferramentas e uma conta/categorias fictícias já no contexto, encerrou após 570 segundos sem chamada. Com uma ferramenta e limite experimental de 64 tokens, terminou após 294 segundos sem texto nem chamada. O Qwen3 4B (2,5 GB, listado com suporte a ferramentas pela [Ollama](https://ollama.com/library/qwen3:4b)) foi testado com uma ferramenta: após 758,6 segundos, gerou um rascunho em inglês sem chamar a ferramenta. O modelo 4B foi removido depois do teste. Os testes dos modelos usaram somente IDs e dados fictícios; nenhuma ferramenta financeira foi executada nem transação gravada. As frases simples de lançamento, por sua vez, têm testes automatizados contra o parser e a API, mas ainda precisam de uma verificação visual na aplicação web antes de usar dados reais.

A variante `qwen3:0.6b` respondeu “OK” em 50,6 segundos na primeira chamada e 25,9 segundos na repetição, mas não concluiu o teste de ferramenta; ela foi removida depois da medição para liberar espaço. Assim, o modelo local ainda não é confiável para tool calling aberto neste host. Os parsers determinísticos têm testes automatizados; a aplicação web ainda precisa de verificação visual após o deploy do código atualizado.

O uso do plano ChatGPT é o caminho escolhido para respostas abertas. Para manter também inferência local sem cota, use Ollama pelo perfil opcional e valide o desempenho antes de confiar em consultas abertas. Essa recomendação é uma inferência baseada nos tempos medidos e nas instruções de CPU expostas pela VM; a documentação da Ollama não garante desempenho para esse hardware. Se não houver outro host disponível, a IA deve permanecer em validação limitada, sem depender dela para operações. O Gemini API tem uma faixa gratuita e suporte oficial a chamadas de ferramentas, mas seus [termos da faixa gratuita](https://ai.google.dev/gemini-api/terms) dizem que entradas e respostas podem ser usadas para melhorar produtos e passar por revisão humana, recomendando que informações sensíveis, confidenciais ou pessoais não sejam enviadas. Essa faixa não é apropriada para dados financeiros pessoais reais.

Ollama desativa recursos Cloud com `OLLAMA_NO_CLOUD=1`. O container não publica `11434`; a API fala com ele pela rede `app` do Compose. A [documentação oficial de tool calling](https://docs.ollama.com/capabilities/tool-calling) descreve mensagens de ferramenta e streaming, e a [API de chat](https://docs.ollama.com/api/chat) documenta os metadados de tokens. A [FAQ da Ollama](https://docs.ollama.com/faq) informa que prompts de instâncias locais não são enviados à Ollama.

## Endpoints autenticados

- `GET /api/ai/status`: disponibilidade do provider e modelos selecionados; não retorna segredos.
- `GET/POST /api/ai/conversations`, `GET/PATCH /api/ai/conversations/{id}`, `POST /api/ai/conversations/{id}/archive`.
- `POST /api/ai/conversations/{id}/messages`: envio em streaming SSE.
- `POST /api/ai/conversations/{id}/tool-calls/{tool_call_id}/confirm` ou `/cancel`.
- `GET/POST /api/ai/memories`, `PATCH/DELETE /api/ai/memories/{id}`, `GET /api/ai/usage`.

Cada endpoint verifica a propriedade pela sessão. IDs de conversas e confirmações pertencentes a outro usuário retornam `404`.

## Desenvolvimento e testes

O provider padrão é chatgpt_plan; nenhum segredo de API é usado. Credenciais OAuth são importadas e renovadas somente no backend. Testes automatizados usam provider falso/transporte simulado e não realizam chamadas externas. O histórico de desempenho medido do Ollama está na seção “Validação histórica do Ollama na VM”.

```powershell
docker compose up
docker compose exec api pytest -q
docker compose exec api ruff check app tests migrations
docker compose exec api mypy --config-file pyproject.toml app
docker compose exec web npm run lint
docker compose exec web npm run typecheck
docker compose exec web npm run build
```

## Checklist manual do assistente

Este checklist descreve critérios de aceite para validação interativa. Os testes automatizados usam provider simulado e não comprovam disponibilidade OAuth nem comportamento visual no host. Antes de testar gravações, use dados identificados como teste e confirme em Preferências ou em `GET /api/ai/status` que o provider está conectado.

1. Envie: “Gastei 87 reais em combustível na moto.” Confirme que o chat usa conta e categoria existentes sem formulário, registra `EXPENSE`, valor `87.00` e data local de `America/Sao_Paulo`; a ação deve aparecer como `local-expense-parser-v1`, sem tokens de modelo.
2. Envie: “Gastei 34 reais em alimentação.” Confirme a categoria Alimentação e que a mensagem é registrada pelo chat, sem selecionar campos.
3. Envie: “Gastei R$ 87,50 de combustível hoje no Sicredi.” Confirme conta, categoria, data local e valor `87.50`.
4. Envie: “Quanto gastei este mês?” Confira valor e período contra o Finance Engine; o modelo esperado é FAST.
5. Envie: “Só alimentação.” Confira se o contexto preserva o período e filtra a categoria, usando FAST.
6. Envie: “E mês passado?” Confira o período anterior sem elevar ao SMART apenas por ser outro mês.
7. Em uma conversa nova, envie “Gastei R$ 100 no mercado.” Depois envie “Na verdade foram R$ 120.” Verifique no banco e na tela que a correção trata o registro anterior, sem criar uma segunda transação. Se a ferramenta exigir confirmação, confirme apenas a alteração proposta e conte os registros antes/depois.
8. Envie: “Passei R$ 350 no Nubank no supermercado.” Confira que existe uma compra de cartão, vinculada à fatura e contada uma vez como despesa.
9. Envie: “Quanto está minha fatura?” Confira o cartão e ciclo corretos.
10. Envie: “Quanto ainda tenho de limite?” Compare o resultado ao limite menos compras/em aberto.
11. Envie: “Transferi R$ 500 do Sicredi para o Inter.” Confira origem, destino e valor registrados uma única vez.
12. Envie: “Quanto gastei hoje?” Confirme que a transferência não aparece nas despesas.
13. Teste “botei 100 de gasolina hj” e confirme valor, data, conta única e categoria combustível. “qnt gastei esse mes” e “passei 240 no Nubank no mercado” passam pelo modelo configurado, não pelo Ollama local automático; confirme que a SophIA consulta os dados e apresenta a compra corretamente antes da confirmação.
14. Envie: “Gastei R$ 200.” Sem conta ou contexto inequívoco, confirme que o assistente pede os dados necessários e não cria um lançamento incompleto ou inventado.
15. Com uma categoria “Combustível” cadastrada, envie “Gastei R$ 57 no carro.” e depois “Combustível”. Confirme que a resposta resolve o esclarecimento sem chamar o modelo e registra exatamente uma despesa.
16. Sem categorias de despesa cadastradas, envie “Gastei R$ 97 em combustível no carro”. Confirme que a SophIA sugere “Combustível”, pergunta se pode criar e não grava nada antes da confirmação.
17. Responda “Sim”. Confirme que cria a categoria e conclui o lançamento original uma única vez, sem chamar o modelo.
18. Repita o fluxo e responda “Crie a categoria Combustível”. Confirme que esse pedido explícito cria ou reutiliza a categoria e continua o lançamento sem duplicá-lo.
19. Envie “Gastei R$ 7,70 com croissant.” Sem “Alimentação” cadastrada, a SophIA deve sugerir essa categoria e aguardar confirmação. Depois responda “Lanche” e “Pode criar lanche deve entrar como Alimentação”. Como categorias ainda são planas, confirme que ela cria/usa “Alimentação”, não uma categoria chamada “Lanche deve entrar como Alimentação”, e registra uma única despesa.
20. Com uma categoria pendente, envie uma frase sem relação com categorias, como “Responda apenas: teste de conexão.” Confirme que ela não é usada como nome de categoria nem cria um lançamento.
21. Com um cartão de teste, peça: “Cadastre as faturas do cartão Gold: novembro/2026 R$ 654,63, dezembro/2026 R$ 519,63 e janeiro/2027 R$ 519,63.” Confira os valores e o cartão no resumo de confirmação. Antes de confirmar, nenhuma fatura nova deve ser gravada. Depois, cada ciclo deve ter o total informado, sem compras artificiais e sem aumento de despesas históricas. Se houver uma compra já cadastrada no ciclo, ela deve ser subtraída do total informado para calcular a dívida inicial; confirme que o total da fatura não aumentou em dobro. O pagamento posterior reduz o saldo da conta e da fatura, sem criar nova despesa.
22. Em uma base de teste, peça: “Crie a categoria Educação, e registre um gasto fixo, começando por 11/26 e finalizando até 04/28, gasto fixo programado de 282 reais, que é pago via pix, vencimento dia 08 de todo mês.” Confira que a categoria pedida é criada e que o chat mostra uma prévia mensal de R$ 282,00, primeira ocorrência em 08/11/2026, última em 08/04/2028 e Pix nas observações. O parser determinístico deve preparar a confirmação sem chamar o modelo. Antes da confirmação, não deve existir regra, ocorrência ou despesa. Depois, a regra aparece em Programados, as ocorrências permanecem previstas e saldo/despesas continuam iguais. Marque uma ocorrência de teste como paga e confira que somente então aparece uma despesa.

Nos diagnósticos, confira timestamp, conversa, modelo, ferramenta, status, duração, tokens de entrada/cache/saída, estimativa de custo e erro resumido. Faça ainda tentativas com OAuth desconectado, revogado ou inválido e, quando disponível, cenários de limite compartilhado, timeout/rede e falha de ferramenta. Em cada cenário, a mensagem deve ser amigável e nenhum erro deve afirmar que um lançamento foi concluído.

## Segurança a validar

- A resposta de `GET /api/ai/status` informa provider e modelos sem retornar segredos; nenhum endpoint web expõe credenciais OAuth ou tokens do provider.
- Cookies de sessão não entram no diagnóstico nem no conteúdo encaminhado ao provider.
- Cada conversa, registro e ferramenta usa o usuário obtido da sessão; o modelo não fornece nem escolhe `user_id`.
- Ferramentas continuam validando ownership em consultas e gravações.
- Logs e respostas de diagnóstico não contêm chave, token de sessão ou prompt interno.
