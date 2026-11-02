"""Testes do grafo inteiro (Supervisor + nós + router), com agentes e LLM mockados.

Os testes de test_supervisor.py olham uma decisão por vez; aqui o app compilado roda do START ao
END, e conferimos o caminho percorrido: é o mesmo que o scripts/e2e.py valida com APIs reais.
"""
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from fluxo_financeiro.graph.graph import app
from fluxo_financeiro.shared.types import RouteDecision, SinalAnomalia

WORKERS = {"YFinance", "Analyzer", "Investigator"}


def _agente(texto):
    agente = MagicMock()
    agente.invoke.return_value = {"messages": [AIMessage(content=texto)]}
    return agente


def _decisao(proximo, tarefa=None):
    return RouteDecision(reasoning=f"vai para {proximo}", next_agent=proximo, task_for_agent=tarefa)


@pytest.fixture
def grafo_mockado():
    """Troca os 3 agentes, o detector de anomalias e o LLM do Supervisor por mocks.

    O detector por padrão não acha nada (o LLM decide a Etapa 4); cada teste pode trocar o
    return_value de mocks["sinais"]. Sem esse mock, o nó do YFinance iria ao yfinance de verdade.
    """
    mocks = {
        "YFinance": _agente("Dados para VALE3.SA: P/L 74.7x, ROE 0.3%"),
        "Analyzer": _agente("análise de notícias"),
        "Investigator": _agente("- Causa identificada: prejuízo no 4T25"),
    }
    with patch("fluxo_financeiro.graph.graph.yfinance_agent", mocks["YFinance"]), \
         patch("fluxo_financeiro.graph.graph.analyzer_agent", mocks["Analyzer"]), \
         patch("fluxo_financeiro.graph.graph.investigator_agent", mocks["Investigator"]), \
         patch("fluxo_financeiro.graph.graph.detectar_sinais_anomalia", return_value=[]) as sinais, \
         patch("fluxo_financeiro.graph.supervisor.llm") as llm:
        mocks["sinais"] = sinais
        mocks["decisoes"] = llm.with_structured_output.return_value.invoke
        yield mocks


def _rodar():
    return app.invoke({"messages": [HumanMessage(content="Analise a ação VALE3")]})


def _quem_falou(resultado):
    return [m.name for m in resultado["messages"] if m.name in WORKERS]


def test_sinal_em_codigo_aciona_investigator_sem_llm(grafo_mockado):
    """Com sinal de anomalia calculado em código, a Etapa 4 vai para o Investigator pelo guard."""
    queda = SinalAnomalia(tipo="queda_lucro", descricao="O lucro líquido de VALE3.SA caiu 35% contra o ano anterior.")
    grafo_mockado["sinais"].return_value = [queda]
    grafo_mockado["decisoes"].side_effect = [
        _decisao("YFinance", "Colete os dados da VALE3"),
        _decisao("Analyzer", "Busque informações sobre o setor de mineração"),
    ]

    resultado = _rodar()

    assert _quem_falou(resultado) == ["YFinance", "Analyzer", "Analyzer", "Investigator"]
    grafo_mockado["sinais"].assert_called_once_with("VALE3")  # ticker extraído do pedido
    # Etapas 2 e 4 e o FINISH final são guards: o LLM só decide as etapas 1 e 3
    assert grafo_mockado["decisoes"].call_count == 2
    # O sinal aparece na mensagem do YFinance e vira a tarefa do Investigator
    msg_yfinance = next(m for m in resultado["messages"] if m.name == "YFinance")
    assert "SINAIS DE ANOMALIA" in msg_yfinance.content
    tarefa = grafo_mockado["Investigator"].invoke.call_args.args[0]["messages"][-1]
    assert tarefa.name == "Supervisor"
    assert queda.descricao in tarefa.content


def test_llm_pode_acionar_investigator_mesmo_sem_sinal(grafo_mockado):
    """Sem sinal calculado, o LLM ainda pode julgar que há algo a investigar (Etapa 4 pelo LLM)."""
    grafo_mockado["decisoes"].side_effect = [
        _decisao("YFinance", "Colete os dados da VALE3"),
        _decisao("Analyzer", "Busque informações sobre o setor de mineração"),
        _decisao("Investigator", "Investigue o ROE de 0,3% da VALE3"),
    ]

    resultado = _rodar()

    assert _quem_falou(resultado) == ["YFinance", "Analyzer", "Analyzer", "Investigator"]
    assert resultado["messages"][-1].content == "- Causa identificada: prejuízo no 4T25"
    assert resultado["loop_count"] == 5
    # Só 3 decisões passam pelo LLM: a etapa 2 e o FINISH final são guards em código
    assert grafo_mockado["decisoes"].call_count == 3
    # O Investigator recebe a tarefa do Supervisor como última mensagem do histórico
    historico = grafo_mockado["Investigator"].invoke.call_args.args[0]["messages"]
    assert historico[-1].name == "Supervisor"
    assert historico[-1].content == "Investigue o ROE de 0,3% da VALE3"


def test_fluxo_sem_anomalia_nao_chama_o_investigator(grafo_mockado):
    """Sem anomalia, a etapa 4 vai direto para FINISH."""
    grafo_mockado["decisoes"].side_effect = [
        _decisao("YFinance", "Colete os dados da WEGE3"),
        _decisao("Analyzer", "Busque informações sobre o setor de automação"),
        _decisao("FINISH"),
    ]

    resultado = _rodar()

    assert _quem_falou(resultado) == ["YFinance", "Analyzer", "Analyzer"]
    assert resultado["loop_count"] == 4
    grafo_mockado["Investigator"].invoke.assert_not_called()


def test_hard_stop_segura_llm_que_nunca_encerra(grafo_mockado):
    """Se o LLM nunca escolhe FINISH, o hard stop (loop_count >= 6) encerra o grafo."""
    grafo_mockado["decisoes"].return_value = _decisao("Analyzer", "Busque mais notícias")

    resultado = _rodar()

    assert resultado["loop_count"] == 7  # 6 passagens + a do hard stop
    assert len(_quem_falou(resultado)) == 6
