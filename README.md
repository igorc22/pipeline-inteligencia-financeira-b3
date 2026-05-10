# Pipeline de Inteligência Financeira — B3

Sistema multi-agente com LLM para análise de ações da B3 usando LangGraph, yfinance e Claude.

## Visão Geral

Um **Supervisor** central orquestra dois agentes:

- **YFinance Agent** — coleta dados de mercado (preço, P/L, ROE, DY, histórico) e calcula Piotroski F-Score
- **Analyzer Agent** — busca notícias recentes e sintetiza uma análise em 1 parágrafo

```
Usuário → Supervisor → YFinance Agent → Supervisor → Analyzer Agent → Supervisor → FINISH
```

## Instalação

```bash
# Instalar dependências
uv sync

# Configurar variáveis de ambiente
cp .env.example .env  # adicione ANTHROPIC_API_KEY e NEWS_API_KEY
```

## Como Usar

```bash
# Análise completa de uma ação
python main.py

# Via código
python -c "
from langchain_core.messages import HumanMessage
from fluxo_financeiro import app

result = app.invoke({'messages': [HumanMessage('Analise WEGE3')]})
print(result['messages'][-1].content)
"
```

## Testar

### Testes Unitários (sem API, rápidos)

```bash
# Rodar todos os testes
pytest tests/ -v

# Por camada
pytest tests/tools/ -v       # ferramentas de dados
pytest tests/agents/ -v      # agentes
pytest tests/graph/ -v       # roteamento do supervisor

# Com cobertura
pytest tests/ --cov=fluxo_financeiro --cov-report=html
```

**Resultado esperado:** 11 testes passando em ~2s (todos mockados, sem chamadas de rede).

### Testar Tools Individualmente (chamadas reais)

```bash
# Dados de mercado: preço, P/L, ROE, DY, histórico 5 dias
python -c "
from fluxo_financeiro.tools.financial_data import buscar_dados_acao_b3
print(buscar_dados_acao_b3.invoke('WEGE3'))
"

# Piotroski F-Score (0-9): análise fundamentalista trimestral
python -c "
from fluxo_financeiro.tools.financial_data import calcular_piotroski_score
print(calcular_piotroski_score.invoke('WEGE3'))
"

# Notícias recentes (requer NEWS_API_KEY no .env)
python -c "
from fluxo_financeiro.tools.news import buscar_noticias
print(buscar_noticias.invoke('WEG Equipamentos'))
"
```

### Testar Agente Collector Diretamente

```bash
# Pedido de dados de mercado → usa buscar_dados_acao_b3
python -c "
from langchain_core.messages import HumanMessage
from fluxo_financeiro.agents.collectors import yfinance_agent
result = yfinance_agent.invoke({'messages': [HumanMessage('Qual o preço atual da PETR4?')]})
print(result['messages'][-1].content)
"

# Pedido fundamentalista → usa calcular_piotroski_score
python -c "
from langchain_core.messages import HumanMessage
from fluxo_financeiro.agents.collectors import yfinance_agent
result = yfinance_agent.invoke({'messages': [HumanMessage('A WEGE3 tem bons fundamentos?')]})
print(result['messages'][-1].content)
"
```

### Verificar Imports

```bash
python -c "from fluxo_financeiro import app; print('OK:', type(app).__name__)"
```

## Estrutura

```
fluxo_financeiro/
├── shared/         # config, tipos, utils (zero dependências internas)
├── tools/          # buscar_dados_acao_b3, calcular_piotroski_score, buscar_noticias
├── agents/         # yfinance_agent (collector), analyzer_agent
└── graph/          # supervisor + StateGraph
```

## Variáveis de Ambiente

```
ANTHROPIC_API_KEY=sk-ant-...   # obrigatório
NEWS_API_KEY=...               # obrigatório para buscar_noticias
```

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Orquestração | LangGraph 1.x |
| LLM | Claude Haiku (langchain-anthropic) |
| Dados de mercado | yfinance |
| Notícias | NewsAPI |
| Testes | pytest |
| Ambiente | uv, python-dotenv |
