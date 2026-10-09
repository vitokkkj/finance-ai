# ADR 0002: Escopo e limites de confiança conversacional

## Status

Aceito.

## Decisão

Um relato claro de movimento já ocorrido autoriza a SophIA a registrá-lo sem pedir uma segunda confirmação. Quando faltarem dados necessários ou houver ambiguidade, a SophIA deve perguntar antes de gravar; correções de transações existentes exigem confirmação explícita. Se o relato omitir conta ou cartão, a SophIA pode usar a preferência padrão configurada quando ela for compatível com a forma de pagamento descrita, deve informar qual destino escolheu e permitir correção; se não houver preferência adequada ou a forma de pagamento continuar ambígua, deve perguntar antes de gravar. Respostas financeiras devem ser concisas, indicar período e filtros considerados e incluir uma divisão útil quando ajudar a interpretar o resultado. Avisos proativos são opt-in, explicam sua base e nunca executam ações financeiras. A primeira oferta de avisos limita-se a lembretes objetivos de fechamento/vencimento de faturas e compromissos registrados; cada tipo é configurável e começa desligado. Avisos baseados em variações de gastos não fazem parte dessa primeira etapa. A antecedência dos avisos é configurável nas Preferências. Eles ficam também numa área “Avisos” do aplicativo e podem ser entregues externamente conforme o canal escolhido. A preferência de entrega é WhatsApp se houver caminho oficial viável; se não, e-mail na fase web e notificações push quando houver aplicativo móvel. Notificações externas podem incluir o nome do cartão ou compromisso, vencimento e valor. A integração e sua viabilidade operacional ainda precisam ser avaliadas antes da implementação; esta decisão cobre avisos, não o uso do WhatsApp como canal de conversa financeira.

A SophIA também pode explicar conceitos de finanças pessoais no Brasil, deixando explícita a distinção entre educação financeira geral e fatos calculados a partir dos registros do usuário. Quando solicitada, pode oferecer sugestões não vinculantes de orçamento e organização baseadas nesses dados; a decisão continua com o usuário.

## Consequências

- O registro conversacional tem pouco atrito para relatos completos, sem transformar intenção futura em movimento realizado.
- A SophIA deve distinguir um relato do usuário sobre algo já ocorrido da autorização para alterar um registro existente.
- Conta padrão e cartão principal são preferências explícitas: só preenchem relatos compatíveis com a forma de pagamento, e a SophIA informa a escolha; ambiguidade restante exige pergunta antes do registro.
- A apresentação de valores continua baseada em dados calculados pelo Finance Engine.
- Nenhum aviso proativo é enviado antes de sua ativação explícita, e avisos não podem modificar dados financeiros.
- Os primeiros avisos opt-in cobrem apenas datas de faturas e compromissos registrados; cada tipo começa desligado, sem avisos iniciais inferidos de variações de gastos.
- A preferência de canal é WhatsApp se houver uma opção oficial viável; caso contrário, e-mail na fase web e push em um futuro aplicativo móvel. O canal e a integração ainda não foram implementados.
- O prazo de antecedência é configurável nas Preferências; os avisos ficam numa área própria dentro do aplicativo e as notificações externas podem incluir nome do cartão/compromisso, data e valor.
- A integração de mensagens cobre somente a entrega de avisos proativos; o canal de conversa financeira continua sendo o app web/móvel.
- Explicações conceituais não devem ser apresentadas como resultados calculados sobre as finanças pessoais do usuário.
- Sugestões baseadas nos dados pessoais devem ser identificadas como opções, não como fatos ou decisões já tomadas.
