"""Testes do grafo inteiro (Supervisor + nós + router), com agentes e LLM mockados.

Os testes de test_supervisor.py olham uma decisão por vez; aqui o app compilado roda do START ao
END, e conferimos o caminho percorrido: é o mesmo que o scripts/e2e.py valida com APIs reais.
"""
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from fluxo_financeiro.agents.consolidator import LIMITACAO_PERFIL_RESERVA
from fluxo_financeiro.graph.graph import app
from fluxo_financeiro.shared.types import RelatorioFinal, RouteDecision, SinalAnomalia
from fluxo_financeiro.tools.financial_data import AVISO_PERFIL_RESERVA

WORKERS = {"YFinance", "Analyzer", "Investigator"}
RELATORIO = RelatorioFinal(resumo="Resumo da análise.", indicadores=["P/L: 74,7x"], contexto="notícias",
                           riscos=["minério"], limitacoes=[])


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
    O LLM do Consolidador também é mockado (mocks["consolidador"]): sem ele, todo teste daqui
    chamaria o Gemini de verdade no fim do fluxo.
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
         patch("fluxo_financeiro.graph.supervisor.llm") as llm,          patch("fluxo_financeiro.agents.consolidator.llm") as llm_consolidador:
        llm_consolidador.with_structured_output.return_value.invoke.return_value = RELATORIO
        mocks["consolidador"] = llm_consolidador
        mocks["sinais"] = sinais
        mocks["decisoes"] = llm.with_structured_output.return_value.invoke
        yield mocks


def _rodar():
    return app.invoke({"messages": [HumanMessage(content="Analise a ação VALE3")]})


def _quem_falou(resultado):
    return [m.name for m in resultado["messages"] if m.name in WORKERS]


def test_sinal_em_codigo_aciona_investigator_sem_llm(grafo_mockado):
    """Confere que, com sinal de anomalia calculado em código, a Etapa 4 vai para o Investigator pelo guard."""
    queda = SinalAnomalia(tipo="queda_lucro", descricao="O lucro líquido de VALE3.SA caiu 35% contra o ano anterior.")
    grafo_mockado["sinais"].return_value = [queda]
    grafo_mockado["decisoes"].side_effect = [
        _decisao("YFinance", "Colete os dados da VALE3"),
    ]

    resultado = _rodar()

    assert _quem_falou(resultado) == ["YFinance", "Analyzer", "Analyzer", "Investigator"]
    assert resultado["messages"][-1].name == "Consolidador"
    assert resultado["loop_count"] == 5
    grafo_mockado["sinais"].assert_called_once_with("VALE3")  # ticker extraído do pedido
    # Etapas 2, 3 e 4 e o FINISH final são guards: o LLM só decide a etapa 1
    assert grafo_mockado["decisoes"].call_count == 1
    # O sinal aparece na mensagem do YFinance e vira a tarefa do Investigator
    msg_yfinance = next(m for m in resultado["messages"] if m.name == "YFinance")
    assert "SINAIS DE ANOMALIA" in msg_yfinance.content
    tarefa = grafo_mockado["Investigator"].invoke.call_args.args[0]["messages"][-1]
    assert tarefa.name == "Supervisor"
    assert queda.descricao in tarefa.content


def test_llm_pode_acionar_investigator_mesmo_sem_sinal(grafo_mockado):
    """Confere que, sem sinal calculado, o LLM ainda pode mandar investigar (Etapa 4 pelo LLM)."""
    grafo_mockado["decisoes"].side_effect = [
        _decisao("YFinance", "Colete os dados da VALE3"),
        _decisao("Investigator", "Investigue o ROE de 0,3% da VALE3"),
    ]

    resultado = _rodar()

    assert _quem_falou(resultado) == ["YFinance", "Analyzer", "Analyzer", "Investigator"]
    final = resultado["messages"][-1]
    assert final.name == "Consolidador"
    assert "- Causa identificada: prejuízo no 4T25" in final.content  # diagnóstico copiado
    assert resultado["relatorio"].diagnostico == "- Causa identificada: prejuízo no 4T25"
    assert resultado["loop_count"] == 5
    # Só 2 decisões passam pelo LLM (etapas 1 e 4): as etapas 2 e 3 e o FINISH final são guards
    assert grafo_mockado["decisoes"].call_count == 2
    # O Investigator recebe a tarefa do Supervisor como última mensagem do histórico
    historico = grafo_mockado["Investigator"].invoke.call_args.args[0]["messages"]
    assert historico[-1].name == "Supervisor"
    assert historico[-1].content == "Investigue o ROE de 0,3% da VALE3"


def _yfinance_com_saida_da_tool(saida_da_tool, resposta_final):
    """Agente do YFinance falso cuja resposta final pode ter perdido a linha "Fonte:" da tool.

    Como o create_agent, devolve o histórico recebido seguido das mensagens novas.
    """
    agente = MagicMock()
    agente.invoke.side_effect = lambda entrada: {"messages": [
        *entrada["messages"],
        ToolMessage(content=saida_da_tool, tool_call_id="1", name="buscar_dados_acao_b3"),
        AIMessage(content=resposta_final),
    ]}
    return agente


def test_aviso_da_reserva_chega_ao_relatorio_mesmo_se_o_agente_resumir(grafo_mockado):
    """Confere que o aviso da reserva vai para a mensagem e para as limitações mesmo que o LLM do YFinance o omita."""
    grafo_mockado["decisoes"].side_effect = [_decisao("YFinance", "Colete os dados da VALE3"), _decisao("FINISH")]
    agente = _yfinance_com_saida_da_tool(f"Dados para VALE3.SA: P/L 74.7x\n{AVISO_PERFIL_RESERVA}\n",
                                         "Dados para VALE3.SA: P/L 74.7x")

    with patch("fluxo_financeiro.graph.graph.yfinance_agent", agente):
        resultado = _rodar()

    msg_yfinance = next(m for m in resultado["messages"] if m.name == "YFinance")
    assert msg_yfinance.text.count(AVISO_PERFIL_RESERVA) == 1
    assert LIMITACAO_PERFIL_RESERVA in resultado["relatorio"].limitacoes


def test_aviso_da_reserva_nao_repete_nem_aparece_com_a_brapi(grafo_mockado):
    """Confere que o aviso não é duplicado quando o agente já o repassou, nem acrescentado quando a Brapi respondeu."""
    grafo_mockado["decisoes"].side_effect = [_decisao("YFinance", "Colete os dados da VALE3"), _decisao("FINISH")] * 2
    copiado = f"Dados para VALE3.SA: P/L 74.7x\n{AVISO_PERFIL_RESERVA}"
    with patch("fluxo_financeiro.graph.graph.yfinance_agent", _yfinance_com_saida_da_tool(copiado, copiado)):
        resultado = _rodar()
    msg_yfinance = next(m for m in resultado["messages"] if m.name == "YFinance")
    assert msg_yfinance.text.count(AVISO_PERFIL_RESERVA) == 1

    com_brapi = "Dados para VALE3.SA: P/L 74.7x\nFonte: cotação e perfil da Brapi; P/L, ROE, DY e histórico do yfinance."
    with patch("fluxo_financeiro.graph.graph.yfinance_agent", _yfinance_com_saida_da_tool(com_brapi, "P/L 74.7x")):
        resultado = _rodar()
    msg_yfinance = next(m for m in resultado["messages"] if m.name == "YFinance")
    assert AVISO_PERFIL_RESERVA not in msg_yfinance.text
    assert LIMITACAO_PERFIL_RESERVA not in resultado["relatorio"].limitacoes


def test_fluxo_sem_anomalia_nao_chama_o_investigator(grafo_mockado):
    """Confere que, sem anomalia, a etapa 4 vai direto para FINISH."""
    grafo_mockado["decisoes"].side_effect = [
        _decisao("YFinance", "Colete os dados da WEGE3"),
        _decisao("FINISH"),
    ]

    resultado = _rodar()

    assert _quem_falou(resultado) == ["YFinance", "Analyzer", "Analyzer"]
    assert resultado["messages"][-1].name == "Consolidador"
    assert resultado["relatorio"].diagnostico is None
    assert resultado["loop_count"] == 4
    grafo_mockado["Investigator"].invoke.assert_not_called()


def test_hard_stop_segura_llm_que_nunca_encerra(grafo_mockado):
    """Confere que o hard stop (loop_count >= 6) encerra o grafo quando o LLM nunca escolhe FINISH."""
    grafo_mockado["decisoes"].return_value = _decisao("Analyzer", "Busque mais notícias")

    resultado = _rodar()
    assert resultado["decidido_por"] == "hard_stop"

    assert resultado["loop_count"] == 7  # 6 passagens + a do hard stop
    assert len(_quem_falou(resultado)) == 6
    assert resultado["messages"][-1].name == "Consolidador"  # o hard stop também consolida


def test_falha_do_consolidador_nao_perde_a_analise(grafo_mockado):
    """Confere que, com erro no LLM do Consolidador, a resposta final vira a junção das respostas dos agentes."""
    grafo_mockado["decisoes"].side_effect = [
        _decisao("YFinance", "Colete os dados da VALE3"),
        _decisao("FINISH"),
    ]
    grafo_mockado["consolidador"].with_structured_output.return_value.invoke.side_effect = Exception("429")

    resultado = _rodar()

    assert _quem_falou(resultado) == ["YFinance", "Analyzer", "Analyzer"]
    final = resultado["messages"][-1]
    assert final.name == "Consolidador"
    assert "análise de notícias" in final.content and "P/L 74.7x" in final.content
    assert resultado["relatorio"] is None
