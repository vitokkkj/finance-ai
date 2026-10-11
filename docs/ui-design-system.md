# Identidade visual e experiência

A SophIA — sua assistente financeira — começa pela conversa: ao entrar, a pessoa vê uma saudação curta, sugestões relacionadas às contas e cartões cadastrados e o campo para perguntar. A conversa anterior não abre automaticamente; fica disponível em **Conversas recentes**. Uma nova conversa só é persistida quando a primeira mensagem é enviada.

A visão geral financeira permanece como uma área própria. Na conversa, o painel lateral fica oculto quando não há assunto financeiro identificável, e pode ser recolhido quando está aberto. Os controles de recolher a navegação e abrir o contexto financeiro ficam no próprio menu lateral, com rótulos explícitos. Quando existe contexto, muda conforme o assunto:

O composer permite anexar até quatro imagens quando o ChatGPT conectado está ativo. Cada anexo tem prévia e ação para remover; a interface informa que os arquivos serão enviados para análise e não serão salvos no histórico. As páginas de Preferências e Minha conta rolam dentro da área principal e mantêm espaço ao final para que o último conteúdo e as ações continuem acessíveis.

Categorias aparecem em grupos separados de **Despesas** e **Receitas**, com contagem e acento de cor próprios para reduzir a confusão entre o tipo e o nome de cada categoria.

- cartão: limite, fechamento, vencimento e fatura mais recente;
- conta: saldo e movimentações associadas;
- gastos: total, categorias e comparação com o mês anterior; quando a conversa pede outro período, o painel segue esse período;
- sem assunto identificável: o painel não é exibido; a home mantém apenas um resumo compacto.

Em telas estreitas, a conversa ocupa a área principal, a navegação vira drawer e o contexto abre como sheet inferior. No estado inicial, o composer fica logo abaixo das sugestões. Depois da primeira mensagem, permanece junto à borda inferior, inclusive com a sheet aberta. A lista de conversas mantém títulos em uma linha com reticências, marcador próprio alinhado ao texto e estado selecionado visível nos temas claro e escuro. O menu mantém rótulos à direita dos ícones. A conta pode receber uma foto circular, redimensionada no navegador e normalizada no servidor.

A Visão Geral destaca o saldo de contas correntes. Poupança e outros tipos aparecem em grupos separados, com saldo realizado e projetado. A área “A pagar” separa atrasados, próximos sete dias e restante do mês; receitas previstas e projeção não se confundem com valores realizados. Conversas recentes recebem um título curto: o provedor sugere o título quando o modelo atende a primeira mensagem, e o parser local usa um resumo determinístico quando já consegue interpretá-la. A sugestão do modelo usa uma chamada breve da mesma conexão ChatGPT e conta no limite de uso do Plus, sem cobrança da API. O usuário pode renomear ou arquivar conversas pela sidebar; títulos longos ficam em uma linha e são truncados visualmente.

## Componentes de resposta

Respostas estruturadas usam um conjunto compacto de componentes para resumo financeiro, categorias, lançamentos, transferências, saldo de contas, cartões, faturas, confirmação, erro e sucesso. As informações são apresentadas a partir dos dados estruturados enviados pela API; o frontend não recalcula totais nem altera a semântica de transferências, compras ou pagamentos de fatura.

## Direção editorial

A conversa permanece como a home, com o histórico no primeiro plano e sugestões apresentadas como linhas compactas. A direção visual usa fundo de papel quente, verde-floresta para ações, tons de argila para despesas e linhas finas em lugar de painéis decorativos. Geist Sans é usada em toda a interface, inclusive em títulos, controles e valores financeiros; os valores usam também algarismos tabulares para facilitar a comparação.

Os tokens dessa direção ficam em `apps/web/src/app/editorial-design.css`, carregado depois das regras base em `globals.css` e `design-system.css`. A paleta oficial usa verde principal `#315E49`, verde escuro `#173B2C`, verde secundário `#4E8068`, creme `#F5F3EB`, branco quente `#FFFEF9` e texto escuro `#08261C`. A marca do símbolo vem da imagem oficial em `apps/web/public/sophia-logo-mark.png`; o favicon e o ícone instalável usam o símbolo em `apps/web/public/icon.svg`. Novas cores, fontes, bordas e estados devem usar os tokens semânticos existentes, com contraste de texto legível em ambos os temas.

## Tema

Claro e escuro são definidos por variáveis CSS. O seletor fica em Preferências e salva a escolha em `localStorage` neste navegador, com a chave `finance-ai-theme`; não há sincronização dessa escolha com o backend. Foco visível, contraste, responsividade e respeito à preferência `prefers-reduced-motion` fazem parte dos estilos comuns.

## Personalização explícita

Em **Preferências da SophIA**, **Como a SophIA trabalha com você** permite configurar explicitamente estilo de resposta, conta padrão, cartão principal, comportamento diante de ambiguidades e proatividade. As escolhas ficam como uma preferência explícita na memória existente e só são salvas mediante confirmação. Em **Memórias da SophIA**, a pessoa pode guardar referências livres. Nada é aprendido automaticamente em silêncio, e essas preferências não alteram lançamentos financeiros.

## Escopo

A Visão geral, Lançamentos, Contas, Cartões, Categorias e Preferências compartilham a direção editorial, com hierarquia e densidade adequadas a cada tela. O redesign usa componentes e dados existentes; não altera regras de cálculo ou semântica financeira.

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
