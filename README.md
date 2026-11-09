# Pipeline de Inteligência Financeira (B3)

Sistema multi-agente com LLM para análise de ações da B3 usando LangGraph, yfinance e Gemini.

## Chaves de API

| Variável | Onde conseguir | Obrigatória? |
|---|---|---|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey): entre com a conta Google e clique em **Create API key** | Sim: é o LLM de todos os agentes e a busca na web |
| `NEWS_API_KEY` | [newsapi.org/register](https://newsapi.org/register): o plano gratuito (Developer) basta | Só para `buscar_noticias`, a reserva da busca na web |
| `TAVILY_API_KEY` | [tavily.com](https://tavily.com): crie uma conta e copie a chave do painel | Não: só com `BUSCA_PROVEDOR=tavily`, para a busca na web usar a Tavily em vez do Google. Cada busca gasta créditos da conta da Tavily |
| `BRAPI_API_KEY` | [brapi.dev](https://brapi.dev): crie uma conta e gere o token no painel; o plano gratuito basta | Não: confere se o ticker existe e traz cotação, setor da B3 e descrição em português. Sem ele, tudo vem do yfinance |
| `LANGSMITH_API_KEY` | [smith.langchain.com](https://smith.langchain.com): **Settings → API Keys → Create API Key** | Não: só para ver os traces de cada análise |

A busca na web usa o Google Search pelo Gemini e só funciona com **faturamento ativo** no projeto da chave (crédito pré-pago no AI Studio serve; o crédito de boas-vindas do Google Cloud, não). Sem faturamento, o LLM continua funcionando, mas as buscas devolvem erro e as notícias ficam só com a NewsAPI. A outra saída é a Tavily: com `BUSCA_PROVEDOR=tavily` e a `TAVILY_API_KEY`, todas as buscas na web vão para ela, e o Gemini fica só como LLM. Com `tavily` e sem a chave, o log avisa e a busca continua no Google.

## Visão Geral

Um **Supervisor** central orquestra três agentes, e um **Consolidador** fecha toda análise com um relatório:

- **YFinance Agent**: coleta dados de mercado (cotação, setor, valor de mercado e os maiores do setor pela Brapi; P/L, ROE, DY e histórico pelo yfinance) e tem tools para métricas de risco (Sharpe, Sortino, Max Drawdown, VaR, Beta, Alpha) e Piotroski F-Score. Em código, sem depender do LLM, a resposta dele ganha a SELIC, o CDI e o IPCA de 12 meses do Banco Central
- **Analyzer Agent**: busca notícias da empresa e do setor numa passagem só (busca na web pelo Google Search ou pela Tavily, com a NewsAPI de reserva); com anomalia, roda em paralelo com o Investigator
- **Investigator Agent** *(condicional)*: acionado só quando o Supervisor detecta uma anomalia; é um subgrafo de pesquisa que lê o histórico trimestral, gera até 3 perguntas sobre a causa, faz uma busca por pergunta em paralelo e passa o diagnóstico por um crítico, que pode pedir até 2 voltas de busca a mais
- **Consolidador** *(sempre no fim)*: junta dados, notícias, setor e diagnóstico num relatório (resumo, indicadores da empresa e da economia, riscos e limitações), sem recomendação de compra ou venda

```
Usuário → Supervisor → YFinance → Supervisor → Analyzer (empresa e setor) [+ Investigator em paralelo,
        se há sinal de anomalia] → Supervisor → [Investigator → Supervisor] → FINISH → Consolidador
```

Desenhos completos (fluxo, decisões do Supervisor, camadas e serviços) em [`docs/arquitetura.md`](docs/arquitetura.md). A história de por que o projeto ficou assim, decisão por decisão, está em [`docs/decisoes.md`](docs/decisoes.md).

## Instalação

```bash
uv sync
```

Copie `.env.example` para `.env` e preencha:

```
GEMINI_API_KEY=...            # obrigatório (LLM e busca na web)
NEWS_API_KEY=...               # obrigatório para buscar_noticias
BRAPI_API_KEY=...              # opcional: token da Brapi (plano gratuito); sem ele, tudo vem do yfinance
LOG_LEVEL=INFO                 # opcional
# BUSCA_PROVEDOR=google        # opcional: google (padrão, Gemini com Google Search) ou tavily
TAVILY_API_KEY=...             # opcional: só com BUSCA_PROVEDOR=tavily
# LLM_MODEL=gemini-3.5-flash-lite  # opcional: modelo dos agentes (padrão: gemini-3.5-flash-lite)

# opcional: sanitização por IA do texto que volta das buscas
SANITIZACAO_ATIVA=false        # true liga a checagem de injeção (gasta 1 chamada a mais por busca)
# SANITIZACAO_MODELO=gemini-3.5-flash-lite  # modelo do classificador (padrão: o mesmo de LLM_MODEL)

# opcional: tracing no LangSmith
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_AGENT_ID=pipeline-b3      # não use junto com LANGSMITH_PROJECT
LANGSMITH_AGENT_ENVIRONMENT=local    # local, development, staging ou production

# evals (grupo dev)
DEEPEVAL_TELEMETRY_OPT_OUT=1         # desliga a telemetria da deepeval
# EVAL_MODELO=gemini-3.8-flash       # opcional: modelo do juiz (padrão: gemini-3.8-flash)
```

Onde tirar cada chave: veja [Chaves de API](#chaves-de-api), no topo.

## Segurança das entradas

- **Ticker:** a CLI e o dashboard só aceitam o código da B3 inteiro (ex: `VALE3`, `TAEE11`, com ou sem `.SA`). Qualquer outra coisa é recusada antes de o grafo rodar. Um código no formato certo que a Brapi diz não existir também é recusado, com uma sugestão quando ela acha uma (`WEGE4` → "Você quis dizer WEGE3?"). Se a Brapi não responde, a análise segue.
- **Texto de fora** (busca na web, NewsAPI, descrição da empresa no yfinance): chega aos agentes dentro de `<conteudo_externo>`, com `<` e `>` escapados, e todo prompt diz que esse conteúdo é dado, nunca instrução. Sempre ligado, sem custo.
- **Checagem por IA** (`SANITIZACAO_ATIVA=true`): antes de chegar aos agentes, o resultado de cada busca passa por um classificador (Gemini Flash-Lite) que diz se o texto tenta dar ordens ao sistema; se sim, ele é trocado por um aviso e entra nas limitações do relatório. Desligada por padrão, para economizar chamadas. O modelo pode ser trocado com `SANITIZACAO_MODELO`.

## Limitações conhecidas

- As regras de anomalia (lucro mais de 30% abaixo do mesmo trimestre do ano anterior, prejuízo, Piotroski de 3 ou menos) foram calibradas olhando poucos tickers, basicamente VALE3 e WEGE3. Os limites são constantes em `fluxo_financeiro/tools/anomalias.py`.
- No plano gratuito da Brapi, os demonstrativos, os dividendos e os indicadores voltam com 403 (só PETR4, VALE3, MGLU3 e ITUB4, os tickers de teste, trazem tudo). Por isso trimestrais, Piotroski, anomalias e métricas de risco vêm só do yfinance.
- O yfinance demora para publicar os trimestres: em 02/11/2026, a VALE3 ainda aparecia com o 2T26 como último trimestre, um mês depois do fim do 3T26.
- O agente YFinance escolhe as tools pelo texto do pedido. Com "Analise a ação X", às vezes ele chama só a de preço e múltiplos, e o relatório sai sem risco e Piotroski.
- Sem faturamento na chave do Gemini, a busca na web falha (erro 429) e as notícias dependem da NewsAPI, que acha pouca coisa sobre ações brasileiras.
- O classificador da sanitização também é um LLM e pode errar para os dois lados.

## Próximos passos

- Docker e docker-compose, e deploy na AWS
- Banco de dados para registrar cada análise (entrada, saída, data e hora)
- Checkpointer e cache de dados frescos
- LiteLLM na frente do modelo
- No fim, expor o pipeline como um agente A2A, para um futuro fluxo de análise de carteira descobrir e chamar

## Como Usar

Os atalhos principais estão no `Makefile` (`make help` lista todos). No Windows, instale o make com `winget install ezwinports.make`.

```bash
make test          # testes unitários (mockados)
make streamlit     # dashboard em http://localhost:8501 (cada análise gasta créditos)
make e2e TICKER=X  # roda o grafo real para um ticker (gasta créditos)
make e2e-sanitizacao  # VALE3 com a checagem de injeção ligada (uma chamada a mais por busca)
```

Sem make:

```bash
# CLI interativa
uv run python main.py

# Dashboard → http://localhost:8501
uv run streamlit run dashboard/app.py
```

O dashboard tem três abas: **Relatório** (resumo, indicadores em quadros, riscos, limitações, notícias e diagnóstico), **Como foi feito** (o caminho da análise desenhado, quem decidiu cada passo e a entrada/saída de cada agente) e **State (JSON)**. Só o botão **Analisar** roda o grafo.

Via código:

```python
from langchain_core.messages import HumanMessage
from fluxo_financeiro import app

result = app.invoke({"messages": [HumanMessage("Analise WEGE3")]})
print(result["messages"][-1].content)
```

## Testes

```bash
uv run pytest tests/ -v           # todos (mockados, sem rede)
uv run pytest tests/tools/ -v     # por camada: tools/, agents/, graph/
```

### Teste end-to-end (chamadas reais)

```bash
uv run python scripts/e2e.py VALE3 --espera-investigator      # ticker com anomalia
uv run python scripts/e2e.py WEGE3 --espera-sem-investigator  # ticker estável
BUSCA_PROVEDOR=tavily uv run python scripts/e2e.py VALE3 --espera-investigator  # o mesmo, com a busca na Tavily
```

Mostra o caminho que o grafo percorreu, as decisões do Supervisor e sai com código 1 se o comportamento não for o esperado.

### Evals (chamadas reais)

Um LLM-juiz (`gemini-3.8-flash`, com a `deepeval`) confere o texto de cada agente contra o que ele tinha em mãos: fidelidade do Analyzer, do Investigator e do Consolidador, diagnóstico do Investigator, cobertura e relevância do relatório e a neutralidade (sem recomendação de compra ou venda). Ficam fora do `pytest` comum (marcador `eval`).

```bash
make eval-fixtures        # grava uma análise real da VALE3 e da WEGE3 em tests/evals/fixtures/ (~US$ 0,02 cada)
make eval-fixtures-tavily # as mesmas análises com a busca na Tavily, em vale3_tavily.json e wege3_tavily.json
make eval FIXTURE=vale3   # roda os evals numa fixture (~US$ 0,12 a 0,16 na VALE3, ~US$ 0,07 a 0,09 na WEGE3)
make -k eval-todos        # as duas fixtures (o -k deixa a WEGE3 rodar mesmo se a VALE3 reprovar)
```

Toda nota vai para `tests/evals/notas.csv` (passando ou não, com o custo e o juiz). Uma reprovação grava entrada, saída, vereditos e contexto em `tests/evals/_falhas/`. A cobertura do Consolidador registra a nota mas não reprova a suíte: na primeira rodada, quase todos os itens que ela apontou eram erro do juiz. Ela lê a entrada sem o sumário do negócio, que o relatório não precisa repetir. Cada fidelidade grava também uma nota rígida, que conta como falha o que a fonte não confirma (a nota normal só desconta o que a fonte contradiz); ela não custa chamada nova e não reprova nada.

### Testar tools individualmente (chamadas reais)

```bash
uv run python -c "from fluxo_financeiro.tools.financial_data import buscar_dados_acao_b3; print(buscar_dados_acao_b3.invoke('WEGE3'))"
uv run python -c "from fluxo_financeiro.tools.financial_data import calcular_metricas_risco; print(calcular_metricas_risco.invoke('WEGE3'))"
uv run python -c "from fluxo_financeiro.tools.financial_data import calcular_piotroski_score; print(calcular_piotroski_score.invoke('WEGE3'))"
uv run python -c "from fluxo_financeiro.tools.news import buscar_noticias; print(buscar_noticias.invoke('WEG'))"
uv run python -c "from fluxo_financeiro.tools.investigation import buscar_historico_trimestral; print(buscar_historico_trimestral.invoke('VALE3'))"
```

## Estrutura

```
fluxo_financeiro/
├── shared/    # config (flags), llm (fábrica do Gemini), types, prompts (tag de conteúdo externo), utils (logger, ticker)
├── tools/     # financial_data, news, investigation, web_search, anomalias, sanitizacao, moeda, brapi
├── agents/    # collectors (YFinance), analysts (Analyzer), pesquisa (subgrafo do Investigator), consolidator
└── graph/     # supervisor (guards + LLM) e StateGraph
scripts/       # e2e.py (teste end-to-end com chamadas reais) e gerar_fixture_eval.py (fixtures dos evals)
dashboard/     # app.py (Streamlit) e visao.py (state → o que a tela mostra)
tests/         # espelha fluxo_financeiro/
notebooks/     # fluxo_financeiro/01 a 21: cada peça explicada e rodando com as APIs reais
docs/          # arquitetura.md (diagramas) e decisoes.md (a história das decisões)
```

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Orquestração | LangGraph 1.x |
| LLM | Gemini 3.5 Flash-Lite (langchain-google-genai) |
| Dados de mercado | Brapi (plano gratuito: ticker, cotação, perfil), yfinance (múltiplos, histórico, demonstrativos), API SGS do Banco Central (SELIC meta, CDI anualizado, IPCA de 12 meses) |
| Notícias e busca na web | Google Search (Gemini, padrão) ou Tavily (`BUSCA_PROVEDOR`), NewsAPI de reserva |
| Dashboard | Streamlit (graphviz para o caminho da análise) |
| Observabilidade | LangSmith (tracing de agentes, tools e buscas) |
| Testes | pytest |
| Ambiente | uv, python-dotenv |
