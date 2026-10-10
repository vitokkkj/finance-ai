# Identidade visual e experiência

A SophIA — sua assistente financeira — começa pela conversa: ao entrar, a pessoa vê uma saudação curta, sugestões relacionadas às contas e cartões cadastrados e o campo para perguntar. A conversa anterior não abre automaticamente; fica disponível em **Conversas recentes**. Uma nova conversa só é persistida quando a primeira mensagem é enviada.

A visão geral financeira permanece como uma área própria. Na conversa, o painel lateral fica oculto quando não há assunto financeiro identificável, e pode ser recolhido quando está aberto. Quando existe contexto, muda conforme o assunto:

- cartão: limite, fechamento, vencimento e fatura mais recente;
- conta: saldo e movimentações associadas;
- gastos: total, categorias e comparação com o mês anterior; quando a conversa pede outro período, o painel segue esse período;
- sem assunto identificável: o painel não é exibido; a home mantém apenas um resumo compacto.

Em telas estreitas, a conversa ocupa a área principal, a navegação vira drawer e o contexto abre como sheet inferior. No estado inicial, o composer fica logo abaixo das sugestões. Depois da primeira mensagem, permanece junto à borda inferior, inclusive com a sheet aberta.

A Visão Geral destaca o saldo total e agrupa receitas, despesas e resultado no fluxo mensal. Conversas recentes recebem um título curto derivado da primeira mensagem, sem chamada adicional ao provedor de IA; o usuário pode renomeá-las ou arquivá-las pela sidebar. Títulos longos aparecem com reticências, sem cortar o texto sem indicação.

## Componentes de resposta

Respostas estruturadas usam um conjunto compacto de componentes para resumo financeiro, categorias, lançamentos, transferências, saldo de contas, cartões, faturas, confirmação, erro e sucesso. As informações são apresentadas a partir dos dados estruturados enviados pela API; o frontend não recalcula totais nem altera a semântica de transferências, compras ou pagamentos de fatura.

## Direção editorial

A conversa permanece como a home, com o histórico no primeiro plano e sugestões apresentadas como linhas compactas. A direção visual usa fundo de papel quente, verde-floresta para ações, tons de argila para despesas e linhas finas em lugar de painéis decorativos. Geist Sans é usada em toda a interface, inclusive em títulos, controles e valores financeiros; os valores usam também algarismos tabulares para facilitar a comparação.

Os tokens dessa direção ficam em `apps/web/src/app/editorial-design.css`, carregado depois das regras base em `globals.css` e `design-system.css`. Novas cores, fontes, bordas e estados devem usar os tokens semânticos existentes.

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
