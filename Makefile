# Atalhos do projeto. Uso: make <alvo>   (ex: make test, make serve, make e2e TICKER=PETR4)
# As receitas são comandos simples para funcionar tanto no Git Bash quanto no cmd/PowerShell.

TICKER ?= VALE3

.DEFAULT_GOAL := help
.PHONY: help install test test-tools test-agents test-graph check run serve streamlit e2e e2e-anomalia e2e-estavel notebook clean

help:
	@echo Alvos disponiveis:
	@echo   make install         - instala dependencias (uv sync)
	@echo   make test            - roda todos os testes unitarios (mockados, sem gastar API)
	@echo   make test-tools      - testes so da camada tools/
	@echo   make test-agents     - testes so da camada agents/
	@echo   make test-graph      - testes so do supervisor/router
	@echo   make check           - confere imports e lista os nos do grafo
	@echo   make run             - CLI interativa (main.py)
	@echo   make serve           - sobe API + dashboard em http://127.0.0.1:8000
	@echo   make streamlit       - abre o dashboard em http://localhost:8501 (cada analise GASTA CREDITOS)
	@echo   make e2e TICKER=X    - roda o grafo real para um ticker (GASTA CREDITOS)
	@echo   make e2e-anomalia    - e2e com VALE3, espera o Investigator ativado
	@echo   make e2e-estavel     - e2e com WEGE3, espera o Investigator NAO ativado
	@echo   make notebook        - abre o Jupyter
	@echo   make clean           - apaga caches (__pycache__, .pytest_cache)

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

serve:
	uv run python serve.py

streamlit:
	uv run streamlit run dashboard/app.py

e2e:
	uv run python scripts/e2e.py $(TICKER)

e2e-anomalia:
	uv run python scripts/e2e.py VALE3 --espera-investigator

e2e-estavel:
	uv run python scripts/e2e.py WEGE3 --espera-sem-investigator

notebook:
	uv run jupyter notebook

clean:
	uv run python -c "import pathlib, shutil; [shutil.rmtree(p, ignore_errors=True) for p in [*pathlib.Path('.').rglob('__pycache__'), pathlib.Path('.pytest_cache')] if '.venv' not in p.parts]"
