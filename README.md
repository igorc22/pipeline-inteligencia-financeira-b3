# Pipeline de Inteligência Financeira — B3

Sistema multi-agente com LLM para análise de ações da B3 usando LangGraph, yfinance e Gemini.

## Visão Geral

Um **Supervisor** central orquestra três agentes, e um **Consolidador** fecha toda análise com um relatório:

- **YFinance Agent**: coleta dados de mercado (preço, P/L, ROE, DY, histórico), métricas de risco (Sharpe, Sortino, Max Drawdown, VaR, Beta, Alpha) e Piotroski F-Score
- **Analyzer Agent**: busca notícias (Google Search via Gemini, com a NewsAPI de reserva) em duas passagens, uma sobre a empresa e outra sobre o setor
- **Investigator Agent** *(condicional)*: acionado só quando o Supervisor detecta uma anomalia; busca fatos relevantes e histórico trimestral para explicar a causa
- **Consolidador** *(sempre no fim)*: junta dados, notícias, setor e diagnóstico num relatório (resumo, indicadores, riscos e limitações), sem recomendação de compra ou venda

```
Usuário → Supervisor → YFinance → Supervisor → Analyzer (empresa) → Supervisor
        → Analyzer (setor) → Supervisor → [Investigator → Supervisor] → FINISH → Consolidador
```

Desenhos completos (fluxo, decisões do Supervisor, camadas e serviços) em [`docs/arquitetura.md`](docs/arquitetura.md); o porquê de cada escolha em [`docs/decisoes.md`](docs/decisoes.md).

## Instalação

```bash
uv sync
```

Copie `.env.example` para `.env` e preencha:

```
GEMINI_API_KEY=...            # obrigatório (LLM e busca na web)
NEWS_API_KEY=...               # obrigatório para buscar_noticias
LOG_LEVEL=INFO                 # opcional

# opcional: tracing no LangSmith
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_AGENT_ID=pipeline-b3      # não use junto com LANGSMITH_PROJECT
LANGSMITH_AGENT_ENVIRONMENT=local    # local, development, staging ou production
```

A busca na web (Google Search) exige faturamento ativo no projeto da chave do Gemini. Sem isso, as tools de busca devolvem erro e o fluxo segue só com a NewsAPI e os dados do yfinance.

## Como Usar

Os atalhos principais estão no `Makefile` (`make help` lista todos). No Windows, instale o make com `winget install ezwinports.make`.

```bash
make test          # testes unitários (mockados)
make streamlit     # dashboard em http://localhost:8501 (cada análise gasta créditos)
make serve         # API (SSE)
make e2e TICKER=X  # roda o grafo real para um ticker (gasta créditos)
```

Sem make:

```bash
# CLI interativa
uv run python main.py

# Dashboard → http://localhost:8501
uv run streamlit run dashboard/app.py

# API → http://127.0.0.1:8000/analyze?ticker=WEGE3
uv run python serve.py
```

O dashboard tem três abas: **Relatório** (resumo, indicadores em quadros, riscos, limitações, notícias e diagnóstico), **Como foi feito** (o caminho da análise desenhado, quem decidiu cada passo e a entrada/saída de cada agente) e **State (JSON)**. Só o botão **Analisar** roda o grafo.

A API expõe `GET /analyze?ticker=WEGE3`: stream SSE com cada passo do grafo.

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
```

Mostra o caminho que o grafo percorreu, as decisões do Supervisor e sai com código 1 se o comportamento não for o esperado.

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
├── shared/    # config, tipos (MessagesState, RouteDecision), logger
├── tools/     # financial_data, news, investigation
├── agents/    # collectors (YFinance), analysts (Analyzer), investigators (Investigator), consolidator
└── graph/     # supervisor (guards + LLM) e StateGraph
api/           # FastAPI com streaming SSE
scripts/       # e2e.py (teste end-to-end com chamadas reais)
dashboard/     # app.py (Streamlit) e visao.py (state → o que a tela mostra)
tests/         # espelha fluxo_financeiro/
```

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Orquestração | LangGraph 1.x |
| LLM | Gemini 3.5 Flash-Lite (langchain-google-genai) |
| Dados de mercado | yfinance, API SGS do Banco Central |
| Notícias | NewsAPI, Google Search (Gemini) |
| Dashboard | Streamlit (graphviz para o caminho da análise) |
| API | FastAPI + uvicorn (SSE) |
| Observabilidade | LangSmith (tracing de agentes, tools e buscas) |
| Testes | pytest |
| Ambiente | uv, python-dotenv |
