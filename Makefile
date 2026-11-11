# Atalhos do projeto. Uso: make <alvo>   (ex: make test, make streamlit, make e2e TICKER=PETR4)
# As receitas são comandos simples para funcionar tanto no Git Bash quanto no cmd/PowerShell.

TICKER ?= VALE3
FIXTURE ?= vale3

.DEFAULT_GOAL := help
.PHONY: help install test test-tools test-agents test-graph check run streamlit e2e e2e-anomalia e2e-estavel e2e-sanitizacao eval-fixtures eval-fixtures-tavily eval eval-vale3 eval-wege3 eval-todos notebook docker-up docker-dev docker-down docker-logs clean

help:
	@echo Alvos disponiveis:
	@echo   make install         - instala dependencias com uv sync
	@echo   make test            - roda todos os testes unitarios, mockados e sem gastar API
	@echo   make test-tools      - testes so da camada tools/
	@echo   make test-agents     - testes so da camada agents/
	@echo   make test-graph      - testes so do supervisor/router
	@echo   make check           - confere imports e lista os nos do grafo
	@echo   make run             - CLI interativa, main.py
	@echo   make streamlit       - abre o dashboard em http://localhost:8501, cada analise GASTA CREDITOS
	@echo   make e2e TICKER=X    - roda o grafo real para um ticker, GASTA CREDITOS
	@echo   make e2e-anomalia    - e2e com VALE3, espera o Investigator ativado
	@echo   make e2e-estavel     - e2e com WEGE3, espera o Investigator NAO ativado
	@echo   make e2e-sanitizacao - e2e com VALE3 e a sanitizacao por IA ligada, uma chamada a mais por busca
	@echo   make eval-fixtures   - gera as fixtures dos evals com analises reais de VALE3 e WEGE3, GASTA CREDITOS
	@echo   make eval-fixtures-tavily - as mesmas fixtures com a busca na Tavily, arquivos _tavily, GASTA CREDITOS
	@echo   make eval FIXTURE=X  - roda os evals com LLM-juiz numa fixture, padrao vale3, GASTA CREDITOS
	@echo   make eval-vale3      - evals na fixture da VALE3, com Investigator, GASTA CREDITOS
	@echo   make eval-wege3      - evals na fixture da WEGE3, sem Investigator, GASTA CREDITOS
	@echo   make -k eval-todos   - evals nas duas fixtures, o -k roda a WEGE3 mesmo se a VALE3 reprovar, GASTA CREDITOS
	@echo   make notebook        - abre o Jupyter
	@echo   make docker-up       - dashboard num container em http://localhost:8501, em segundo plano, GASTA CREDITOS por analise
	@echo   make docker-dev      - o mesmo com recarga ao salvar: o codigo vai para o container sem rebuild
	@echo   make docker-down     - para e remove o container
	@echo   make docker-logs     - acompanha o log do container
	@echo   make clean           - apaga os caches __pycache__ e .pytest_cache

install:
	uv sync

test:
	uv run pytest tests/ -v

test-tools:
	uv run pytest tests/tools/ -v

test-agents:
	uv run pytest tests/agents/ -v

test-graph:
	uv run pytest tests/graph/ -v

check:
	uv run python -c "from fluxo_financeiro import app; print(sorted(app.get_graph().nodes))"

run:
	uv run python main.py

streamlit:
	uv run streamlit run dashboard/app.py

e2e:
	uv run python scripts/e2e.py $(TICKER)

e2e-anomalia:
	uv run python scripts/e2e.py VALE3 --espera-investigator

e2e-estavel:
	uv run python scripts/e2e.py WEGE3 --espera-sem-investigator

# A flag vale só para este alvo (variável exportada por alvo: funciona no Git Bash e no cmd)
e2e-sanitizacao: export SANITIZACAO_ATIVA = true
e2e-sanitizacao:
	uv run python scripts/e2e.py VALE3 --espera-investigator

eval-fixtures:
	uv run python scripts/gerar_fixture_eval.py VALE3
	uv run python scripts/gerar_fixture_eval.py WEGE3

# Mesmas analises com a busca na Tavily: grava vale3_tavily.json e wege3_tavily.json, sem tocar nas do Google
eval-fixtures-tavily: export BUSCA_PROVEDOR = tavily
eval-fixtures-tavily:
	uv run python scripts/gerar_fixture_eval.py VALE3
	uv run python scripts/gerar_fixture_eval.py WEGE3

# Evals com LLM-juiz (GASTAM CREDITOS). Variaveis exportadas por alvo, como no e2e-sanitizacao
eval: export EVAL_FIXTURE = $(FIXTURE)
eval: export DEEPEVAL_TELEMETRY_OPT_OUT = 1
eval:
	uv run pytest tests/evals -m eval -v

eval-vale3: export EVAL_FIXTURE = vale3
eval-vale3: export DEEPEVAL_TELEMETRY_OPT_OUT = 1
eval-vale3:
	uv run pytest tests/evals -m eval -v

eval-wege3: export EVAL_FIXTURE = wege3
eval-wege3: export DEEPEVAL_TELEMETRY_OPT_OUT = 1
eval-wege3:
	uv run pytest tests/evals -m eval -v

# Use com -k (make -k eval-todos): sem ele, uma reprovacao na VALE3 impede a WEGE3 de rodar
eval-todos: eval-vale3 eval-wege3

notebook:
	uv run jupyter notebook

docker-up:
	docker compose up --build -d

docker-dev:
	docker compose up --build --watch

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f dashboard

clean:
	uv run python -c "import pathlib, shutil; [shutil.rmtree(p, ignore_errors=True) for p in [*pathlib.Path('.').rglob('__pycache__'), pathlib.Path('.pytest_cache')] if '.venv' not in p.parts]"
