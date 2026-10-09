# Preferências explícitas do assistente

O assistente mantém conversas e preferências explícitas no PostgreSQL. As preferências ficam vinculadas ao `users.id` autenticado e podem ser criadas, alteradas ou removidas em Preferências. O usuário também pode pedir no chat para o assistente lembrar algo. Cada preferência aceita até 500 caracteres; o prompt usa no máximo as 20 mais recentes.

Preferências ajudam em escolhas conversacionais recorrentes, por exemplo, uma conta padrão declarada pelo usuário, uma associação explícita entre estabelecimento e categoria ou o nível de detalhe desejado. A mensagem atual prevalece. Uma conta padrão ou cartão principal só preenche um destino omitido quando for compatível com a forma de pagamento descrita; a SophIA informa a escolha e permite correção. Sem preferência adequada ou com ambiguidade sobre a forma de pagamento, pergunta antes de gravar. Se uma preferência não corresponder a uma conta ou categoria existente, o assistente pergunta. Preferências não criam fatos, não alteram lançamentos e não autorizam uma operação sem as confirmações financeiras necessárias.

No primeiro uso, uma única conta cadastrada pode iniciar como conta padrão e um único cartão como cartão principal. Havendo mais de uma opção, a SophIA pede que o usuário escolha; ambas as preferências permanecem visíveis e editáveis.

Não há aprendizado automático de hábitos, memória vetorial, embeddings ou inferência de preferências. Um padrão detectado futuramente deverá ser mostrado como sugestão revisável, separado dos registros financeiros e das preferências explícitas.

Consultas monetárias continuam usando resultados estruturados das ferramentas validadas e do Finance Engine. Segredos, credenciais bancárias, números completos de conta/cartão e dados pessoais desnecessários não devem ser enviados ao modelo. Provedor, modelos e preços são configuração do backend; nomes de modelos não pertencem à lógica financeira.
