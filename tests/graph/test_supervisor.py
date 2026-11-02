from unittest.mock import patch

import pytest
from langchain_core.messages import HumanMessage

from fluxo_financeiro.graph.supervisor import supervisor_node, router
from fluxo_financeiro.shared.types import MessagesState, RouteDecision


def _state(messages, loop_count=0, next_agent="YFinance") -> MessagesState:
    return {
        "messages": messages,
        "next_agent": next_agent,
        "loop_count": loop_count,
        "supervisor_reasoning": "",
    }


HISTORICO_ETAPA_4 = [
    HumanMessage(content="Analise VALE3"),
    HumanMessage(content="Lucro líquido caiu 62% no trimestre...", name="YFinance"),
    HumanMessage(content="Busque notícias recentes...", name="Supervisor"),
    HumanMessage(content="noticias da empresa...", name="Analyzer"),
    HumanMessage(content="Busque informações sobre o setor de mineração...", name="Supervisor"),
    HumanMessage(content="contexto setorial...", name="Analyzer"),
]


@pytest.fixture
def mock_llm():
    """LLM do supervisor mockado: nenhum teste deste arquivo pode chamar a API real."""
    with patch("fluxo_financeiro.graph.supervisor.llm") as llm:
        yield llm


def _llm_decide(mock_llm, decision: RouteDecision):
    mock_llm.with_structured_output.return_value.invoke.return_value = decision


# ---------------------------------------------------------------------------
# Hard stop e guards (decididos em código, sem LLM)
# ---------------------------------------------------------------------------

def test_supervisor_node_hard_stop(mock_llm):
    """Test que o supervisor encerra em loop_count >= 6 sem consultar o LLM."""
    result = supervisor_node(_state([HumanMessage(content="test")], loop_count=6))
    assert result["next_agent"] == "FINISH"
    mock_llm.with_structured_output.assert_not_called()


def test_supervisor_guard_yfinance_para_analyzer(mock_llm):
    """Test que, com dados coletados e sem Analyzer, o guard força o Analyzer com tarefa de notícias."""
    state = _state([
        HumanMessage(content="Analise WEGE3"),
        HumanMessage(content="dados...", name="YFinance"),
    ], loop_count=1)

    result = supervisor_node(state)

    assert result["next_agent"] == "Analyzer"
    assert result["messages"][0].name == "Supervisor"
    assert "notícias" in result["messages"][0].content
    mock_llm.with_structured_output.assert_not_called()


def test_supervisor_guard_investigator_retorna_finish(mock_llm):
    """Test que se Investigator já existe no histórico, supervisor retorna FINISH sem LLM."""
    state = _state(
        HISTORICO_ETAPA_4 + [HumanMessage(content="causa identificada...", name="Investigator")],
        loop_count=4,
        next_agent="Investigator",
    )
    result = supervisor_node(state)
    assert result["next_agent"] == "FINISH"
    mock_llm.with_structured_output.assert_not_called()


# ---------------------------------------------------------------------------
# Decisões do LLM (Etapa 4)
# ---------------------------------------------------------------------------

def test_supervisor_etapa4_roteia_investigator_com_tarefa(mock_llm):
    """Test que, quando o LLM detecta anomalia, a task_for_agent entra no histórico como Supervisor."""
    tarefa = "Investigue a seguinte anomalia identificada na análise de VALE3: queda de 62% no lucro."
    _llm_decide(mock_llm, RouteDecision(
        reasoning="Queda de lucro sem explicação nas notícias.",
        next_agent="Investigator",
        task_for_agent=tarefa,
    ))

    result = supervisor_node(_state(HISTORICO_ETAPA_4, loop_count=3))

    assert result["next_agent"] == "Investigator"
    assert result["supervisor_reasoning"] == "Queda de lucro sem explicação nas notícias."
    assert result["messages"][0].name == "Supervisor"
    assert result["messages"][0].content == tarefa
    assert result["loop_count"] == 1


def test_supervisor_etapa4_sem_anomalia_finaliza_sem_mensagem(mock_llm):
    """Test que FINISH não injeta mensagem do Supervisor no histórico, mesmo se o LLM mandar tarefa."""
    _llm_decide(mock_llm, RouteDecision(
        reasoning="Dados consistentes com as notícias.",
        next_agent="FINISH",
        task_for_agent="(ignorado)",
    ))

    result = supervisor_node(_state(HISTORICO_ETAPA_4, loop_count=3))

    assert result["next_agent"] == "FINISH"
    assert "messages" not in result


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("next_agent, destino", [
    ("YFinance", "YFinance"),
    ("Analyzer", "Analyzer"),
    ("Investigator", "Investigator"),
    ("FINISH", "__end__"),
])
def test_router(next_agent, destino):
    """Test que o router mapeia cada decisão para o nó correto (FINISH → __end__)."""
    assert router(_state([HumanMessage(content="test")], next_agent=next_agent)) == destino
