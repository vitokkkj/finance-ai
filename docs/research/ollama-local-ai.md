# Pesquisa: IA local com Ollama

**Pesquisado em:** 2026-10-09
**Escopo:** documentação oficial da Ollama e da equipe Qwen. Esta nota não altera a aplicação nem representa validação prática do modelo na VM.

## Recomendação inicial

Para evitar cobrança por tokens de API e manter as conversas financeiras dentro da VM, a opção inicial recomendada é executar Ollama localmente em um serviço Docker privado e testar `qwen3:1.7b` (quantização Q4_K_M, cerca de 1,4 GB). O projeto deve chamar a API nativa `POST /api/chat` pela rede interna do Compose. Não publicar a porta 11434 no host e desativar recursos Ollama Cloud com `OLLAMA_NO_CLOUD=1`.

Isso elimina cobrança por chamada de um provedor hospedado, mas não elimina custo de CPU, memória, armazenamento, energia ou tráfego para baixar a imagem e o modelo. A VM tem 4 GiB de RAM; o tamanho de 1,4 GB é o artefato do modelo, não uma garantia de uso total de memória. O uso real e a latência de inferência por CPU precisam ser medidos na VM com os serviços atuais ativos.

## API de chat e tool calling

Ollama documenta a rota nativa `POST /api/chat`, com histórico em `messages`, lista opcional `tools`, opção `stream` e controle de saída de raciocínio `think`. O formato de ferramenta é uma função com `name`, `description` e JSON Schema em `parameters`. A resposta do assistente pode conter `tool_calls`; após executar a ferramenta no backend, o cliente acrescenta a mensagem do assistente e o resultado com papel `tool` ao histórico e envia uma chamada de continuação.

Para streaming com ferramentas, a documentação orienta agregar os trechos de `thinking`, `content` e `tool_calls` recebidos em cada chunk e enviar os campos agregados junto com os resultados de ferramentas na próxima chamada. Não se deve executar uma chamada enquanto seus argumentos ainda estão chegando em partes. O loop e a validação de ownership permanecem no backend da SophIA.

Ao concluir uma resposta, a API nativa fornece `done`, `done_reason`, durações em nanossegundos e contagens de tokens: `prompt_eval_count`, `prompt_eval_cached_count` (quando disponível) e `eval_count`. Esses dados podem alimentar o diagnóstico local, sem custo monetário por token. Na modalidade `stream: true`, a implementação deve preservar os metadados do chunk final, além de agregar os trechos de mensagem.

Como o provider atual da SophIA usa a Responses API da OpenAI, a integração Ollama precisará converter o histórico e a resposta de ferramentas para o formato nativo acima ou adotar um endpoint compatível que tenha sido validado. A documentação da Ollama confirma diretamente a API nativa e o loop de ferramentas; ela é o caminho de menor ambiguidade para a primeira implementação.

## Docker e isolamento

A página oficial de Docker usa a imagem `ollama/ollama` e um volume persistente em `/root/.ollama` para guardar modelos. O exemplo oficial para CPU publica `11434` com `-p`; na SophIA, preservar o volume, mas omitir `ports` no Compose e conectar o serviço apenas à rede interna acessível pela API. Assim, navegador, host e internet não recebem uma porta pública de inferência.

O download do modelo exige conectividade de saída na instalação inicial. Depois de baixado, inferência local usa a VM. A FAQ afirma que a Ollama não vê prompts ou dados quando o serviço roda localmente. Ela também documenta `OLLAMA_NO_CLOUD=1` como forma de desabilitar recursos Cloud; isso deve ser aplicado para evitar que a configuração futura use modelos ou busca hospedados.

## Modelo inicial: Qwen3 1.7B

- O catálogo oficial da Ollama informa que `qwen3:1.7b` ocupa aproximadamente **1,4 GB**, tem janela listada de **40K tokens** e é marcado com suporte a ferramentas. A página do artefato identifica **2,03 bilhões de parâmetros**, quantização **Q4_K_M** e licença **Apache 2.0**.
- O repositório oficial Qwen informa que a família Qwen3 inclui modelos densos de 0,6B e 1,7B, oferece uso de ferramentas e suporta mais de 100 idiomas/dialetos. A equipe publica todos os modelos abertos Qwen3 sob Apache 2.0.
- As afirmações de capacidade e raciocínio publicadas pela equipe são sobre a família/modelos avaliados e não garantem qualidade igual no checkpoint 1.7B quantizado, em português brasileiro ou no fluxo financeiro da SophIA.
- Não encontrei nos materiais oficiais consultados um benchmark reproduzível de latência em CPU para `qwen3:1.7b` no hardware desta VM, nem um benchmark específico para as tarefas financeiras da SophIA. A qualidade em interpretação de lançamentos, perguntas ambíguas, seleção de tools e respostas em pt-BR permanece pendente de teste manual.
- A janela máxima listada não deve virar o contexto padrão. Em uma VM com 4 GiB, começar com um contexto menor e medir RAM, swap, latência e estabilidade; o consumo de memória cresce com contexto e concorrência.

## Privacidade e limites

A documentação da Ollama declara que execuções locais não enviam prompts e dados para `ollama.com`, e apresenta a opção de desabilitar recursos Cloud. Isso não substitui os controles da SophIA: manter sessões, histórico e ownership no PostgreSQL/API; não colocar dados financeiros no frontend além do necessário; não registrar prompts ou secrets; e manter o Ollama sem porta publicada. Logs da API devem evitar conteúdo sensível.

Um modelo local pode alucinar, escolher uma ferramenta errada ou gerar argumentos inválidos. A IA não deve calcular valores financeiros: tools continuam sendo validadas no backend, derivando `user_id` da sessão, aplicando ownership e delegando cálculos ao Finance Engine. Se uma tool falhar, a resposta deve indicar falha sem declarar que a ação foi executada.

## Próximos passos de implementação e validação

1. Adicionar serviço oficial `ollama/ollama` ao Compose da VM, com volume persistente, sem `ports`, acessível só pela API e com recursos Cloud desativados.
2. Baixar `qwen3:1.7b` na VM e medir consumo de RAM/swap e latência com o frontend, API, worker e PostgreSQL ativos.
3. Implementar provider selecionável por configuração e adaptar tool calling ao formato nativo `/api/chat`; manter o provider genérico e preservar o caminho de OpenAI sem ativá-lo.
4. Validar primeiro respostas simples e tool calls com dados financeiros de teste; depois revisar ambiguidades, memória de conversa, erros e pt-BR.
5. Só habilitar o assistente no uso real após verificar que todas as tools mantêm identidade de sessão, ownership e semântica financeira independentemente do modelo.

## Fontes oficiais

- Ollama, [Tool calling](https://docs.ollama.com/capabilities/tool-calling) — esquema de funções, mensagens de continuação, chamadas paralelas e streaming.
- Ollama, [API: Generate a chat message](https://docs.ollama.com/api/chat) — formato `/api/chat`, streaming, `think` e metadados de uso/duração.
- Ollama, [Docker](https://docs.ollama.com/docker) — imagem oficial e armazenamento persistente para execução CPU.
- Ollama, [FAQ](https://docs.ollama.com/faq) — privacidade local, desativação de Cloud, memória/keep-alive e concorrência.
- Ollama, [Qwen3 model library](https://ollama.com/library/qwen3) e [tag Qwen3 1.7B](https://ollama.com/library/qwen3:1.7b) — tamanhos, contexto, quantização, parâmetros e licença listados pelo catálogo.
- Qwen, [repositório oficial Qwen3](https://github.com/QwenLM/Qwen3) — tamanhos da família, ferramentas, capacidades declaradas e licença da família.
- Qwen, [modelo oficial Qwen3-1.7B no Hugging Face](https://huggingface.co/Qwen/Qwen3-1.7B) — identificação do checkpoint e licença Apache 2.0.
