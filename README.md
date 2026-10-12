# SophIA — sua assistente financeira

Aplicação financeira pessoal e privada, administrada por uma conta proprietária. Não há cadastro público. A conta inicial é criada pelo fluxo controlado de bootstrap; depois disso, somente o proprietário autenticado pode criar contas de login adicionais. Todas as contas exigem senha e TOTP individual; os segredos das contas gerenciadas são cifrados com a chave Fernet privada `MFA_ENCRYPTION_KEY`. Os dados financeiros de cada pessoa são isolados pelo usuário autenticado. O Finance Engine calcula saldos, faturas e resumos no backend. A SophIA é a interface principal: conversa com você e consulta ou registra operações financeiras por ferramentas explícitas.

O código está publicado em [vitokkkj/finance-ai](https://github.com/vitokkkj/finance-ai) sob a licença MIT; consulte [LICENSE](LICENSE). A instância da SophIA, as credenciais e os dados financeiros do proprietário continuam privados e ficam fora deste repositório.

## Iniciar o ambiente local

Requisitos: Docker Desktop com Docker Compose ou Docker Engine com o plugin Compose. Node.js e Python não são necessários na máquina host para iniciar a aplicação.

Na primeira execução, crie o arquivo local de ambiente e substitua a senha de desenvolvimento do PostgreSQL por uma senha aleatória composta por letras e números:

```powershell
Copy-Item .env.example .env
```

Para testar contas gerenciadas no ambiente local, gere uma chave Fernet e preencha `MFA_ENCRYPTION_KEY` no `.env` conforme o procedimento em [docs/deployment.md](docs/deployment.md). O valor fica em branco no `.env.example` de propósito; não reutilize a chave local em produção.

Depois, na raiz do projeto, inicie todos os serviços com um único comando:

```powershell
docker compose up
```

Abra <http://localhost:3000>, crie a conta privada e cadastre uma conta e categorias. Nos próximos inícios, `docker compose up` é suficiente. O Compose aplica as migrations antes de iniciar a API.

Use `docker compose up --build` quando alterar dependências ou Dockerfiles.

## Serviços e rede

| Serviço | Responsabilidade | Acesso no host |
| --- | --- | --- |
| `web` | Interface Next.js, filtros e proxy same-origin para a API | `localhost:3000` |
| `api` | Autenticação, operações financeiras e Finance Engine | Somente pela rede Docker |
| `worker` | Processo separado que mantém as ocorrências recorrentes no horizonte de 90 dias | Somente pela rede Docker |
| `caddy` | Cabeçalhos HTTP de segurança e proxy interno para o frontend (produção) | Somente pela rede Docker; sem porta publicada |
| `cloudflared` | Túnel de saída que publica o hostname configurado na Cloudflare (produção) | Somente pela rede Docker; sem porta publicada |
| ollama | Inferência local opcional (Qwen3), iniciada somente com o perfil local-ai | Somente pela rede Docker; sem porta publicada |
| `postgres` | Fonte persistente de usuários e dados financeiros | Somente pela rede Docker interna; sem porta publicada |

Frontend, API, worker, Caddy, cloudflared e PostgreSQL permanecem em serviços separados. A API não publica porta no host. O banco participa somente da rede Docker interna e nunca é publicado externamente.

## Acesso externo na VM

Não exponha a execução local `docker compose up` à internet. Para a VM pública, use exclusivamente o perfil de produção documentado em [docs/deployment.md](docs/deployment.md): Cloudflare Tunnel é a única entrada da aplicação; nenhum serviço Compose publica portas no host. A VM mantém SSH na porta 22; `sophia` continua aceitando senha e o proprietário pode usar `su -`, enquanto `root` aceita somente chave pública. Caddy aplica cabeçalhos de segurança atrás do túnel e todas as contas exigem TOTP individual. API e banco não têm portas públicas; a conta inicial é criada pelo bootstrap controlado com token temporário. Depois, somente o proprietário autenticado pode administrar contas de login, cujos dados financeiros permanecem isolados por usuário. Configure a rota `finance.ruralflow.com.br`, `APP_DOMAIN` e os segredos privados antes de iniciar esse perfil. `MFA_ENCRYPTION_KEY` precisa estar no `.env` privado e em backup separado do banco; a documentação de [deploy](docs/deployment.md) explica geração, perda e rotação da chave. Os backups da VM são gerenciados pelo Proxmox, fora do repositório.

O padrão usa OAuth do plano ChatGPT, sem chave da API e sem fallback para chamadas pagas da API. O repositório já é público sob MIT; a instância, as credenciais OAuth e os dados financeiros continuam privados. O uso feito pela SophIA entra nos limites do próprio plano autorizado e não dá acesso ao histórico ou às memórias do ChatGPT. Confira as permissões e os limites do aplicativo em ChatGPT → Configurações → Uso. Consulte a [documentação oficial de Sign in with ChatGPT](https://developers.openai.com/siwc/token-sharing-open-source) e o guia para [VMs auto-hospedadas](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms).

Para autorizar uma VM, conclua o OAuth neste computador com Python 3.10+ e SSH configurado. O script abre o login oficial, recebe o retorno somente em 127.0.0.1, valida e transfere as credenciais à VM por SSH; a VM guarda os tokens em volume privado com permissão restrita e os renova sozinha:

```powershell
py -3 .\scripts\connect-chatgpt-plan.py --ssh-target <usuario>@<ip-tailscale> --project-dir <diretorio-do-compose> --identity <caminho-da-chave>
```

O computador pode ser desligado após a transferência. A tela Preferências informa se o plano está conectado, os modelos FAST/SMART e o uso registrado. Se a conexão ou a cota falhar, a SophIA pausa as respostas e explica o problema; não usa uma API paga.

O Ollama continua disponível como alternativa local explicitamente iniciada com docker compose --profile local-ai up -d. Ele não é iniciado junto com o plano ChatGPT nem acionado automaticamente como fallback. PostgreSQL continua apenas na rede interna do Compose.

## Funcionalidades atuais

- Contas em BRL com saldo inicial e data-base; contas arquivadas deixam de compor o saldo total, e seu histórico permanece no banco.
- Categorias distintas para receitas e despesas; arquivar uma categoria não apaga os lançamentos existentes.
- As categorias são agrupadas por tipo; abrir uma categoria mostra os lançamentos correspondentes já filtrados.
- Criação, edição, listagem, filtragem e exclusão de lançamentos manuais confirmados.
- Listas extensas usam paginação de 15 itens, incluindo lançamentos, cartões, faturas, ocorrências e conversas.
- Filtros por período, conta, categoria, tipo e texto.
- Dashboard com saldo total, receitas, despesas, resultado do mês, despesas por categoria e lançamentos recentes.
- Isolamento por `users.id` em cada consulta e gravação, com chaves compostas impedindo referências financeiras entre usuários.
- Transferências próprias em um único registro com origem e destino; elas mudam os saldos das duas contas sem criar receita ou despesa.
- Cartões com limite, dia de fechamento e vencimento, além de ciclos de fatura explícitos.
- Compras no cartão associadas a uma fatura. A compra conta como despesa na data da compra e não movimenta uma conta bancária.
- Pagamentos integrais ou parciais associados à fatura e à conta pagadora. Cada pagamento reduz essa conta e o saldo aberto da fatura sem repetir a despesa.
- Importação pelo chat do total de uma ou mais faturas existentes, com confirmação. Compras já cadastradas no ciclo são abatidas do total e somente o saldo restante vira dívida inicial; não são criadas despesas históricas. O pagamento segue o fluxo normal.
- Dashboard com limite usado e disponível e próximo vencimento de cada cartão ativo.
- Conversas privadas persistidas, com histórico, streaming SSE e preferências salvas explicitamente pelo usuário.
- Preferências explícitas do assistente podem ser criadas, editadas e removidas em Preferências; não há aprendizado automático de hábitos.
- Tema claro/escuro, identidade visual e diretrizes de UX estão descritos em [docs/ui-design-system.md](docs/ui-design-system.md); a escolha de tema fica salva localmente no navegador.
- Ferramentas financeiras autenticadas para consultar contas, saldos, lançamentos, categorias, cartões e faturas, e para registrar operações manuais.
- Alterações em lançamentos existentes ficam pendentes até confirmação explícita. Falhas de ferramentas não são apresentadas como operações concluídas.
- Regras de receita/despesa recorrentes com ocorrências previstas até 90 dias à frente, incluindo frequências diária, semanal, mensal e anual.
- Ocorrências não afetam saldos até serem registradas; registrar cria uma única transação confirmada, e ignorar ou encerrar preserva o histórico sem criar movimento.
- A previsão “A pagar” reúne compromissos avulsos, ocorrências recorrentes e faturas abertas por vencimento. O centro de avisos leva ao item correspondente e permite registrar o pagamento após conferência.
- O proprietário cria e administra contas de login em Preferências; não há cadastro público. A API restringe essa administração à sessão do proprietário e bloqueia a exclusão quando a conta tem dados associados. Cada conta gerenciada precisa concluir o pareamento MFA individual antes do primeiro login; o reset exige senha e TOTP do proprietário, revoga as sessões da conta e preserva seus dados financeiros.
- Minha conta permite exportar dados em JSON; Lançamentos aceita o modelo CSV descrito em [docs/importacao-csv.md](docs/importacao-csv.md), com prévia e confirmação explícita.
- O fluxo padrão usa OAuth do ChatGPT exclusivamente no backend e o endpoint Responses API; nenhuma chave da API é configurada. AI_MODEL_FAST e AI_MODEL_SMART são configuráveis por ambiente. O Ollama só inicia com o perfil local-ai e não é fallback automático. Pedidos inequívocos de despesas e recorrências mensais podem ser interpretados por regras determinísticas; pedidos ambíguos seguem para o modelo SMART, que deve sugerir e perguntar antes de executar. Os testes automatizados usam providers e transportes simulados.

Saldo de uma conta ativa é calculado como saldo inicial, mais receitas e transferências recebidas, menos despesas, transferências enviadas e pagamentos de fatura, considerando somente movimentos a partir da data-base. Compras no cartão não movimentam contas. O Finance Engine calcula esses valores no backend. PostgreSQL usa `NUMERIC(14,2)`, Python usa `Decimal` e a API transmite valores monetários em texto decimal. O navegador apenas formata esses textos; não soma valores financeiros.

A tabela `transactions` guarda cada evento uma única vez. Uma transferência é um registro `TRANSFER` com conta de origem e de destino. Uma compra é `CARD_PURCHASE`, com categoria de despesa e vínculo com uma fatura. Um pagamento é `CARD_PAYMENT`, com a conta pagadora e a fatura. Para faturas anteriores ao uso da SophIA, `card_invoices.opening_balance` registra somente a dívida já aberta; o total é esse saldo mais as compras associadas, e o saldo aberto desconta os pagamentos. Esse saldo inicial não é despesa histórica.

O dia de fechamento é inclusivo: uma compra no próprio dia entra na fatura que fecha naquele dia; uma compra no dia seguinte entra no ciclo seguinte. Quando o dia não existe no mês (por exemplo, fechamento 31 em fevereiro), o fechamento usa o último dia do mês. O vencimento usa o dia configurado no mesmo mês apenas se for posterior ao fechamento; caso contrário, fica no mês seguinte, também ajustado ao último dia existente. Ciclos e datas são datas civis em `America/Sao_Paulo`.

Ao importar um saldo de fatura, informe o mês do **vencimento**. Por exemplo, em um cartão que fecha dia 26 e vence dia 10, a fatura com vencimento em novembro corresponde ao ciclo de 27 de setembro a 26 de outubro. A prévia da tela mostra o ciclo calculado antes do registro.

Status da fatura é derivado do ciclo e dos pagamentos: `OPEN` até a data de fechamento, `CLOSED` depois do fechamento, `PARTIALLY_PAID` enquanto houver saldo após pagamento parcial, `PAID` quando o saldo chega a zero e `OVERDUE` após o vencimento enquanto restar saldo. Total comprado, valor pago, saldo aberto, limite utilizado e limite disponível são calculados no Finance Engine.

As datas inseridas representam o dia civil em `America/Sao_Paulo`; os limites do mês são convertidos para instantes com timezone nas consultas. A interface e a moeda são `pt-BR` e BRL.

## Comandos úteis

```powershell
# Estado dos serviços e health checks
docker compose ps

# Logs
docker compose logs -f web api worker postgres

# Versão atual das migrations PostgreSQL
docker compose exec api alembic current

# Testes rápidos com banco SQLite isolado, somente para teste
docker compose exec api pytest -q

# Lint e type checking da API e do worker
docker compose exec api ruff check app tests migrations
docker compose exec api mypy --config-file pyproject.toml app
docker compose exec worker ruff check --no-cache /workspace/worker
docker compose exec worker sh -c 'MYPYPATH=/workspace/apps/api:/workspace/worker mypy --config-file /workspace/apps/api/pyproject.toml --cache-dir=/tmp/mypy_cache /workspace/worker'

# Lint, typecheck e build do frontend
docker compose exec web npm run lint
docker compose exec web npm run typecheck
docker compose exec web npm run build
docker compose exec web npm run test:e2e
```

O E2E padrão usa mocks e dispensa a API. O cenário integrado é habilitado com `E2E_INTEGRATED=1` e precisa de API, banco descartável migrado e `OWNER_TOTP_SECRET` fictício de teste; a CI prepara esses serviços e executa ambos os fluxos. Nunca use segredos de produção em automação.

Para executar a suíte contra PostgreSQL, crie uma vez um banco de teste separado do banco de desenvolvimento e passe sua URL pela variável `TEST_DATABASE_URL`:

```powershell
docker compose exec postgres sh -c 'createdb -U "$POSTGRES_USER" finance_ai_test'
docker compose exec api sh -c 'TEST_DATABASE_URL="${DATABASE_URL%/*}/finance_ai_test" pytest -q'
```

Não aponte `TEST_DATABASE_URL` para o banco de desenvolvimento: os fixtures dos testes recriam as tabelas financeiras do banco indicado. As migrations PostgreSQL podem ser exercitadas em um banco descartável com `alembic upgrade head`, `alembic downgrade base` e novamente `alembic upgrade head`.

## API financeira

- `GET/POST /api/accounts`, `PATCH /api/accounts/{id}`, `POST /api/accounts/{id}/archive`
- `GET/POST /api/categories`, `PATCH /api/categories/{id}`, `POST /api/categories/{id}/archive`
- `GET/POST /api/transactions`, `PATCH/DELETE /api/transactions/{id}`
- `GET/POST /api/transfers`
- `GET/POST /api/cards`, `PATCH /api/cards/{id}`, `POST /api/cards/{id}/archive`
- `PUT /api/cards/{id}/invoices/opening-balance` para registrar o saldo de uma fatura já existente
- `GET /api/cards/{id}/invoices`, `GET /api/invoices/{id}`, `GET /api/invoices/{id}/payments`
- `POST /api/card-purchases`, `POST /api/invoices/{id}/payments`
- `GET /api/dashboard/summary?year=2026&month=10`
- `GET/POST /api/recurrences`, `PATCH /api/recurrences/{id}`, `POST /api/recurrences/{id}/cancel`
- `GET /api/recurrences/occurrences`, `PATCH /api/recurrences/{id}/occurrences/{occurrence_id}`
- `POST /api/recurrences/{id}/occurrences/{occurrence_id}/pay` ou `/skip`
- `GET /api/ai/status`, `GET/POST /api/ai/conversations`, `GET/PATCH /api/ai/conversations/{id}`
- `POST /api/ai/conversations/{id}/messages` (SSE), confirmação/cancelamento de ferramenta e gestão de preferências
- `GET /api/ai/usage`, `GET/DELETE /api/ai/memories`
- `GET /api/export` e `POST /api/imports/transactions/preview`, `POST /api/imports/transactions/confirm`
- `GET /api/ai/diagnostics` somente em desenvolvimento; checklist real e detalhes em [docs/ai-assistant.md](docs/ai-assistant.md)

Todos os endpoints financeiros exigem sessão. O usuário da sessão determina o escopo dos registros; o cliente não pode escolher `user_id`.

## Estrutura principal

```text
apps/
  api/       FastAPI, autenticação, Finance Engine, recorrências, provider/tools de IA, migrations e testes
  web/       Next.js, TypeScript, assistente conversacional, telas financeiras e proxy da API
worker/      Processo Python separado para estender o horizonte de recorrências
docs/        Arquitetura, dados, regras financeiras e integrações planejadas
infra/       Preparação da infraestrutura
docker-compose.yml
AGENTS.md
```

## Primeiro uso e lançamentos manuais

Depois do cadastro privado, a SophIA pede uma conta para acompanhar. O saldo inicial e sua data podem ficar em branco; nesse caso, o saldo do tipo daquela conta permanece indisponível. O valor principal da interface considera apenas contas correntes; poupança e demais tipos ficam separados. O cartão é opcional. Para registrar a primeira receita ou despesa pela interface, será necessário criar uma categoria; o formulário oferece um caminho para criá-la e voltar ao lançamento. Veja [docs/first-use-and-manual-records.md](docs/first-use-and-manual-records.md).

Na VM de teste, use o override para iniciar o frontend sem a barra Next.js Dev Tools e sem autoreload da API:

```bash
docker compose -f docker-compose.yml -f docker-compose.vm.yml up -d --build
```

O `docker compose up` simples continua reservado ao ambiente local de desenvolvimento.

## Limites desta fase e próximos passos

O centro de avisos da aplicação mostra compromissos vencidos e com vencimento nos próximos sete dias, usando os mesmos dados da previsão financeira. Ele atualiza ao abrir a lista, ao voltar para a aba e a cada cinco minutos enquanto a aplicação está aberta. Os avisos não são enviados fora da aplicação; notificações push e e-mail ficam para uma etapa futura. Recorrências cobrem regras e ocorrências previstas; despesas recorrentes não alteram saldos até serem marcadas como pagas. Gestão de financiamentos com amortização, parcelamentos, investimentos e integração Pluggy ainda não foram implementados. O uso do plano ChatGPT via OAuth é o provider padrão, sem chave da API nem fallback pago; o Ollama é uma alternativa local opcional. O parser determinístico cobre frases inequívocas de despesas e programação mensal; pedidos incompletos ou ambíguos seguem para o modelo, com instruções para sugerir e perguntar.

Uma VM Debian pode hospedar a instância pessoal pela internet usando o perfil de produção descrito em [docs/deployment.md](docs/deployment.md). Publique somente o código, nunca `.env`, credenciais, endereços privados ou dados financeiros. Cloudflare Tunnel é a única entrada pública da aplicação; containers não publicam portas no host e API/PostgreSQL permanecem privados. A porta SSH 22 fica aberta por escolha do proprietário; `sophia` aceita senha, o proprietário pode usar `su -`, e `root` aceita somente chave pública dedicada. A exposição pela rede anterior à VM precisa ser verificada separadamente. A interface responsiva pode ser instalada como PWA no iOS; um app nativo pode ser desenvolvido depois reutilizando a API.
