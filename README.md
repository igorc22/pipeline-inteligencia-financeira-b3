# Pipeline de Inteligência Financeira — B3

Sistema multi-agente com LLM para análise de ações da B3 usando LangGraph, yfinance e Claude.

## Visão Geral

Um **Supervisor** central orquestra três agentes:

- **YFinance Agent**: coleta dados de mercado (preço, P/L, ROE, DY, histórico), métricas de risco (Sharpe, Sortino, Max Drawdown, VaR, Beta, Alpha) e Piotroski F-Score
- **Analyzer Agent**: busca notícias (NewsAPI + Anthropic Web Search) em duas passagens, uma sobre a empresa e outra sobre o setor
- **Investigator Agent** *(condicional)*: acionado só quando o Supervisor detecta uma anomalia; busca fatos relevantes e histórico trimestral para explicar a causa

```
Usuário → Supervisor → YFinance → Supervisor → Analyzer (empresa) → Supervisor
        → Analyzer (setor) → Supervisor → [Investigator → Supervisor] → FINISH
```

## Instalação

```bash
uv sync
```

Crie um arquivo `.env` na raiz:

```
ANTHROPIC_API_KEY=sk-ant-...   # obrigatório (LLM e Web Search)
NEWS_API_KEY=...               # obrigatório para buscar_noticias
LOG_LEVEL=INFO                 # opcional
```

## Como Usar

Os atalhos principais estão no `Makefile` (`make help` lista todos). No Windows, instale o make com `winget install ezwinports.make`.

```bash
make test          # testes unitários (mockados)
make serve         # API + dashboard
make e2e TICKER=X  # roda o grafo real para um ticker (gasta créditos)
```

Sem make:

```bash
# CLI interativa
uv run python main.py

# API + dashboard em tempo real → http://127.0.0.1:8000
uv run python serve.py
```

A API expõe:
- `GET /`: dashboard com o grafo animado, o raciocínio do Supervisor e um card por agente
- `GET /analyze?ticker=WEGE3`: stream SSE com cada passo do grafo

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
├── agents/    # collectors (YFinance), analysts (Analyzer), investigators (Investigator)
└── graph/     # supervisor (guards + LLM) e StateGraph
api/           # FastAPI com streaming SSE
scripts/       # e2e.py (teste end-to-end com chamadas reais)
dashboard/     # index.html do dashboard
tests/         # espelha fluxo_financeiro/
```

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Orquestração | LangGraph 1.x |
| LLM | Claude Haiku 4.5 (langchain-anthropic) |
| Dados de mercado | yfinance, API SGS do Banco Central |
| Notícias | NewsAPI, Anthropic Web Search |
| API | FastAPI + uvicorn (SSE) |
| Testes | pytest |
| Ambiente | uv, python-dotenv |
