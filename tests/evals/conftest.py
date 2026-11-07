"""Fixtures dos evals.

NADA da deepeval é importado no nível do módulo. O `-m 'not eval'` do addopts desseleciona DEPOIS da
coleta, e a coleta importa todo módulo de tests/, fora do bloqueio de rede do pytest-socket (que só vale
durante cada teste). Um `from deepeval ... import` aqui em cima rodaria em todo `pytest`, mesmo com zero
evals selecionados: carregaria a telemetria com a rede aberta e, na referência, custou 2,75 s em toda
execução. Por isso o juiz é fixture e o import fica dentro dela. test_helpers.py confere isso pela
árvore sintática de todos os módulos desta pasta.
"""
import os

import pytest

from tests.evals.helpers import (
    FIXTURES_DIR,
    JUIZ_PADRAO,
    TEMPERATURA_JUIZ,
    carregar_fixture,
    medir_e_registrar,
    mensagens,
)

FIXTURE = FIXTURES_DIR / f"{os.getenv('EVAL_FIXTURE', 'vale3')}.json"


@pytest.fixture(scope="session")
def estado():
    """Fixture gerada por scripts/gerar_fixture_eval.py: state final e saídas das tools de cada passagem."""
    return carregar_fixture(FIXTURE)


@pytest.fixture(scope="session")
def pedido(estado):
    """Texto do pedido do usuário (a primeira mensagem sem name)."""
    return next(m.text for m in mensagens(estado) if not m.name)


@pytest.fixture(scope="session")
def juiz():
    """Juiz único, reaproveitado por todas as métricas. Criar o GeminiModel não chama a API.

    Sem passar model=juiz em cada métrica, a deepeval cai no padrão dela (OpenAI) e pede OPENAI_API_KEY.
    EVAL_MODELO troca o modelo; não há fallback para o modelo julgado.

    A chave também é importada aqui: com `pytest tests/evals`, este conftest carrega antes dos filtros
    de aviso do pyproject, e importar fluxo_financeiro no topo traria o grafo inteiro (e um aviso do
    langgraph) para esse momento.
    """
    from deepeval.models import GeminiModel

    from fluxo_financeiro.shared.config import GEMINI_API_KEY

    extras = {} if TEMPERATURA_JUIZ is None else {"temperature": TEMPERATURA_JUIZ}
    return GeminiModel(model=os.getenv("EVAL_MODELO", JUIZ_PADRAO), api_key=GEMINI_API_KEY, **extras)


@pytest.fixture
def medir(request, juiz):
    """Mede, registra no notas.csv e reprova só se a métrica reprovar. A lógica está em helpers."""
    return lambda metric, tc: medir_e_registrar(metric, tc, FIXTURE.stem, request.node.name, juiz.get_model_name())
