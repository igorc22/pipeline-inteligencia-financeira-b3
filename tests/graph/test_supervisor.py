from unittest.mock import patch

import pytest
from langchain_core.messages import HumanMessage

from fluxo_financeiro.graph.supervisor import SUPERVISOR_PROMPT, supervisor_node, router
from fluxo_financeiro.shared.prompts import REGRA_CONTEUDO_EXTERNO
from fluxo_financeiro.shared.types import MessagesState, RouteDecision, SinalAnomalia


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
    assert result["decidido_por"] == "hard_stop"
    assert result["next_agent"] == "FINISH"
    mock_llm.with_structured_output.assert_not_called()


def test_supervisor_guard_yfinance_para_analyzer(mock_llm):
    """Test que, com dados coletados e sem Analyzer, o guard força o Analyzer com tarefa de notícias."""
    state = _state([
        HumanMessage(content="Analise WEGE3"),
        HumanMessage(content="dados...", name="YFinance"),
    ], loop_count=1)

    result = supervisor_node(state)
    assert result["decidido_por"] == "guard"

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
    assert result["decidido_por"] == "guard"
    assert result["next_agent"] == "FINISH"
    mock_llm.with_structured_output.assert_not_called()


QUEDA = SinalAnomalia(tipo="queda_lucro", descricao="Lucro de VALE3.SA caiu 35% contra o ano anterior.")


def test_supervisor_guard_sinais_forca_investigator(mock_llm):
    """Test que, com análise completa e sinal calculado em código, vai ao Investigator sem LLM."""
    state = _state(HISTORICO_ETAPA_4, loop_count=3)
    state["sinais_anomalia"] = [QUEDA]

    result = supervisor_node(state)
    assert result["decidido_por"] == "guard"

    assert result["next_agent"] == "Investigator"
    assert result["messages"][0].name == "Supervisor"
    assert QUEDA.descricao in result["messages"][0].content
    assert "queda_lucro" in result["supervisor_reasoning"]
    mock_llm.with_structured_output.assert_not_called()


def test_supervisor_guard_uma_passagem_do_analyzer_pede_o_setor(mock_llm):
    """Test que, com 1 passagem do Analyzer, o guard pede o contexto do setor sem consultar o LLM (Etapa 3)."""
    state = _state(HISTORICO_ETAPA_4[:4], loop_count=2)  # só 1 mensagem do Analyzer

    result = supervisor_node(state)
    assert result["decidido_por"] == "guard"

    assert result["next_agent"] == "Analyzer"
    tarefa = result["messages"][0]
    assert tarefa.name == "Supervisor"
    assert "setor" in tarefa.content and "VALE3" in tarefa.content
    mock_llm.with_structured_output.assert_not_called()


def test_supervisor_guard_sinais_espera_as_duas_passagens_do_analyzer(mock_llm):
    """Test que o sinal não pula a Etapa 3: com 1 passagem do Analyzer, vai ao setor antes do Investigator."""
    state = _state(HISTORICO_ETAPA_4[:4], loop_count=2)  # só 1 mensagem do Analyzer
    state["sinais_anomalia"] = [QUEDA]

    result = supervisor_node(state)
    assert result["decidido_por"] == "guard"

    assert result["next_agent"] == "Analyzer"
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
    assert result["decidido_por"] == "llm"

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
    assert result["decidido_por"] == "llm"

    assert result["next_agent"] == "FINISH"
    assert "messages" not in result


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("next_agent, destino", [
    ("YFinance", "YFinance"),
    ("Analyzer", "Analyzer"),
    ("Investigator", "Investigator"),
    ("FINISH", "Consolidador"),
])
def test_router(next_agent, destino):
    """Test que o router mapeia cada decisão para o nó correto (FINISH → Consolidador, que vai ao END)."""
    assert router(_state([HumanMessage(content="test")], next_agent=next_agent)) == destino


# ---------------------------------------------------------------------------
# Prompt em XML (D47)
# ---------------------------------------------------------------------------

def test_supervisor_prompt_mantem_contratos():
    """Test que a reescrita em XML manteve o que o pipeline e os guards dependem."""
    for trecho in ("SINAIS DE ANOMALIA", "YFinance", "Analyzer", "Investigator", "FINISH",
                   "Um investidor ficaria com dúvida de POR QUE"):
        assert trecho in SUPERVISOR_PROMPT
    assert REGRA_CONTEUDO_EXTERNO in SUPERVISOR_PROMPT
    assert "<pipeline>" in SUPERVISOR_PROMPT and "</pipeline>" in SUPERVISOR_PROMPT


def test_supervisor_prompt_sem_indentacao_herdada():
    """Test que nenhuma linha do prompt carrega a indentação de 4 espaços do código antigo."""
    assert not any(linha.startswith("    -") for linha in SUPERVISOR_PROMPT.splitlines())


def test_supervisor_envia_o_prompt_como_system_message(mock_llm):
    """Test que a etapa 4 sem sinais manda exatamente o SUPERVISOR_PROMPT como primeira mensagem."""
    _llm_decide(mock_llm, RouteDecision(reasoning="ok", next_agent="FINISH"))

    supervisor_node(_state(HISTORICO_ETAPA_4, loop_count=3))

    mensagens = mock_llm.with_structured_output.return_value.invoke.call_args.args[0]
    assert mensagens[0].content == SUPERVISOR_PROMPT
