# Identidade visual e experiência

A SophIA — sua assistente financeira — começa pela conversa: ao entrar, a pessoa vê uma saudação curta, sugestões relacionadas às contas e cartões cadastrados e o campo para perguntar. A conversa anterior não abre automaticamente; fica disponível em **Conversas recentes**. Uma nova conversa só é persistida quando a primeira mensagem é enviada.

A visão geral financeira permanece como uma área própria. Na conversa, o painel lateral fica oculto quando não há assunto financeiro identificável, e pode ser recolhido quando está aberto. Os controles de recolher a navegação e abrir o contexto financeiro ficam no próprio menu lateral, com rótulos explícitos. Quando existe contexto, muda conforme o assunto:

O composer permite anexar até quatro imagens quando o ChatGPT conectado está ativo. Cada anexo tem prévia e ação para remover; a interface informa que os arquivos serão enviados para análise e não serão salvos no histórico. As páginas de Preferências e Minha conta rolam dentro da área principal e mantêm espaço ao final para que o último conteúdo e as ações continuem acessíveis.

Categorias aparecem em grupos separados, com **Receitas antes de Despesas**, contagem e acento de cor próprios para reduzir a confusão entre o tipo e o nome de cada categoria. Abrir o nome de uma categoria leva aos lançamentos filtrados por ela.

Listas extensas usam a paginação padrão da SophIA, com 15 itens por página e indicação de intervalo/total. Os controles mantêm o estilo visual do sistema, funcionam por teclado e preservam a navegação para o item aberto a partir de um aviso.

Quando uma ação de uma lista abre um formulário de edição fora da área visível, a tela rola até o formulário e move o foco para seu título. O movimento respeita a preferência do sistema por movimento reduzido; manter o foco no título evita abrir o teclado virtual automaticamente. Receitas e Despesas usam a mesma grade de colunas nas tabelas de categorias, deixando a situação alinhada entre os grupos.

- cartão: limite, fechamento, vencimento e fatura mais recente;
- conta: saldo e movimentações associadas;
- gastos: total, categorias e comparação com o mês anterior; quando a conversa pede outro período, o painel segue esse período;
- sem assunto identificável: o painel não é exibido; a home mantém apenas um resumo compacto.

Em telas estreitas, a conversa ocupa a área principal, a navegação vira drawer e o contexto abre como sheet inferior. No estado inicial, o composer fica logo abaixo das sugestões. Depois da primeira mensagem, permanece junto à borda inferior, inclusive com a sheet aberta. A lista de conversas mantém títulos em uma linha com reticências, marcador próprio alinhado ao texto e estado selecionado visível nos temas claro e escuro. O menu mantém rótulos à direita dos ícones. A conta pode receber uma foto circular, redimensionada no navegador e normalizada no servidor.

A Visão Geral destaca o saldo de contas correntes. Poupança e outros tipos aparecem em grupos separados, com saldo realizado e projetado. A área “A pagar” separa atrasados, próximos sete dias e restante do mês; receitas previstas e projeção não se confundem com valores realizados. Conversas recentes recebem um título curto: o provedor sugere o título quando o modelo atende a primeira mensagem, e o parser local usa um resumo determinístico quando já consegue interpretá-la. A sugestão do modelo usa uma chamada breve da mesma conexão ChatGPT e conta no limite de uso do Plus, sem cobrança da API. O usuário pode renomear ou arquivar conversas pela sidebar; títulos longos ficam em uma linha e são truncados visualmente.

O sino **Avisos** no cabeçalho abre uma lista de pagamentos atrasados e vencimentos dos próximos sete dias, com valor, data e conta ou cartão. A contagem do sino reflete avisos ativos, não itens não lidos; pagar ou cancelar uma obrigação remove o aviso quando os dados financeiros são atualizados. A lista reaproveita a previsão da API, atualizada ao abrir, ao retornar à aba e em intervalos de cinco minutos. No celular, o painel se adapta à largura da tela. Estes são avisos dentro da SophIA; push e e-mail ainda não estão incluídos.

## Componentes de resposta

Respostas estruturadas usam um conjunto compacto de componentes para resumo financeiro, categorias, lançamentos, transferências, saldo de contas, cartões, faturas, confirmação, erro e sucesso. As informações são apresentadas a partir dos dados estruturados enviados pela API; o frontend não recalcula totais nem altera a semântica de transferências, compras ou pagamentos de fatura.

O indicador durante a resposta usa um orbe leve em CSS. O aro externo tem arco de contraste e rotação visível de 1,05 s; um ponto percorre o aro e o núcleo pulsa. Com `prefers-reduced-motion: reduce`, as animações param. O texto do estado continua vindo do andamento real da solicitação e das ferramentas financeiras da API. O campo de mensagem e o histórico permanecem na tela; não existe atraso mínimo artificial nem substituição do fluxo de mensagens por uma resposta demonstrativa.

## Direção visual

A conversa continua como a home. A direção baseada no template AI Chat da TailGrids agora forma o sistema visual comum do produto: navegação e histórico em uma barra lateral verde-floresta, conteúdo em uma área de trabalho organizada, superfícies com bordas discretas, cantos arredondados e acentos verdes para ações e seleção. O padrão cobre login e primeiro acesso, chat e respostas estruturadas, Visão geral, Lançamentos, Contas, Cartões e faturas, Programados, Categorias, Preferências e Minha conta. Os tipos de movimentação mantêm suas cores semânticas; o verde não substitui os sinais de receita, despesa, alerta ou erro.

Geist Sans é usada em toda a interface. Valores financeiros usam algarismos tabulares. As telas financeiras continuam exibindo valores e datas fornecidos pela API, sem recálculo no frontend.

Os tokens visuais finais ficam em `apps/web/src/app/sophia-redesign.css`, carregado por último após `globals.css`, `design-system.css` e `editorial-design.css`. A camada editorial anterior continua fornecendo estilos de componentes e a nova camada sobrescreve seus tokens semânticos e tratamentos visuais. A marca usa `apps/web/public/sophia-logo-mark.png`; o favicon e o ícone instalável usam `apps/web/public/icon.svg`.

## Tema e responsividade

Claro e escuro são definidos por variáveis CSS em `sophia-redesign.css`. No tema claro, o conteúdo usa fundo `#F2F6F3`, superfícies brancas, texto `#16251B`, verde principal `#315E49` e navegação `#14221A`. No tema escuro, usa fundo `#141C16`, superfícies `#1C261F`, texto `#F1F6F1`, verde de ação `#A4CDA8` e navegação `#101712`. O seletor em Preferências e no cabeçalho mantém a escolha em `localStorage` no navegador pela chave `finance-ai-theme`; a escolha não é sincronizada com o backend.

Foco visível, contraste, responsividade e a preferência `prefers-reduced-motion` permanecem parte dos estilos comuns. Em telas estreitas, o menu continua como drawer; as páginas financeiras mantêm seu fluxo responsivo e as áreas respeitam os recortes seguros do iPhone. Campos de entrada preservam fonte mínima de 16 px em celular para evitar zoom automático do Safari.

## Personalização explícita

Em **Preferências da SophIA**, **Como a SophIA trabalha com você** permite configurar explicitamente estilo de resposta, conta padrão, cartão principal, comportamento diante de ambiguidades e proatividade. As escolhas ficam como uma preferência explícita na memória existente e só são salvas mediante confirmação. Em **Memórias da SophIA**, a pessoa pode guardar referências livres. Nada é aprendido automaticamente em silêncio, e essas preferências não alteram lançamentos financeiros.

## Escopo

As telas autenticadas e de acesso compartilham a mesma identidade visual, com hierarquia e densidade adequadas a cada fluxo. O redesign usa os componentes e dados existentes; não altera regras de cálculo, autenticação, autorização ou semântica financeira.

## Revisão manual

- Entrar e conferir a home de conversa, sugestões e composer logo abaixo delas; enviar uma primeira mensagem e verificar o composer no rodapé.
- Abrir uma conversa anterior e voltar a **Nova conversa**.
- Conferir o contexto para cartões, contas e gastos; verificar que transferência não aparece como despesa.
- Abrir e fechar o painel contextual no desktop e no sheet em viewport móvel.
- Conferir que o painel some sem contexto identificável e pode ser recolhido quando útil.
- Conferir a hierarquia de saldo e fluxo mensal na Visão Geral, os estados vazios e as ações de renomear/arquivar conversa.
- Conferir os cinco controles explícitos de **Como a SophIA trabalha com você** sem salvar durante a revisão visual.
- Conferir respostas estruturadas, confirmações, estados de erro e sucesso nos temas claro e escuro.
- Conferir navegação por teclado, foco visível, contraste e `prefers-reduced-motion`.
- Conferir o aro girando com movimento normal e estático com movimento reduzido.
- A regressão móvel em Playwright percorre chat, Visão geral, Lançamentos, Contas, Cartões, Programados, Categorias e Preferências em 360, 390 e 430 px; verifica estouro horizontal, posição do compositor e drawer, densidade do histórico, marcador da conversa ativa e quebra de mensagens longas. Safari/iPhone físico ainda exige validação manual.
