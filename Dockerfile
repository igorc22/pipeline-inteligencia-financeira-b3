# syntax=docker/dockerfile:1
# Dashboard em Streamlit numa imagem enxuta. Uso: make docker-up (imagem como ela é)
# ou make docker-dev (recarga ao salvar). As chaves vêm do .env em tempo de execução, nunca da imagem.

ARG PYTHON_VERSION=3.12

# --- builder: monta o .venv com o uv --------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.12 /uv /bin/uv

# Bytecode compilado no build (o primeiro start fica mais rápido), cópia em vez de link (o cache
# é um mount e não existe no estágio final) e o Python da imagem, sem baixar outro.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Só as dependências, antes do código: mexer no código não reinstala nada. Os grupos dev
# (pytest, deepeval) e notebooks (jupyter) ficam de fora. O cache mount guarda os pacotes
# baixados entre builds, então mudar o uv.lock só baixa o que mudou.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-install-project --no-default-groups

# --- runtime: o .venv e o código, sem o uv --------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

# Usuário sem privilégio, com home (o yfinance guarda um cache de fuso horário em ~/.cache)
RUN groupadd --system app && useradd --system --gid app --create-home app

WORKDIR /app

# O pacote não é instalado no .venv: o PYTHONPATH aponta para /app, e é por ele que o Streamlit
# sabe que fluxo_financeiro/ também é código do projeto e recarrega ao salvar (docker compose watch).
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

COPY --from=builder --chown=app:app /app/.venv /app/.venv
# Dono app: o docker compose watch escreve aqui dentro com o usuário do container
COPY --chown=app:app fluxo_financeiro ./fluxo_financeiro
COPY --chown=app:app dashboard ./dashboard

USER app

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4)"]

CMD ["streamlit", "run", "dashboard/app.py"]
