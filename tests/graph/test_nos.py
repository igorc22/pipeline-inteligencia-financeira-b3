"""Testes dos nós dos workers chamados direto: cada um grava a própria saída num campo do state.

Os agentes são mockados em fluxo_financeiro.graph.graph; no YFinance, o detector de anomalias e o
bloco do Banco Central também (sem eles, o nó iria ao yfinance e à API do BCB de verdade).
"""
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from fluxo_financeiro.graph.graph import analyzer_node, investigator_node, yfinance_node
from fluxo_financeiro.shared.types import SinalAnomalia

PEDIDO = HumanMessage("Analise VALE3")


def _agente(texto):
    agente = MagicMock()
    agente.invoke.return_value = {"messages": [AIMessage(content=texto)]}
    return agente


def _rodar_analyzer(state, texto="análise de notícias"):
    with patch("fluxo_financeiro.graph.graph.analyzer_agent", _agente(texto)):
        return analyzer_node(state)


def test_yfinance_grava_dados_mercado():
    """Confere que o YFinance grava em dados_mercado o mesmo texto da mensagem, já com o bloco de sinais."""
    sinal = SinalAnomalia(tipo="prejuizo", descricao="prejuízo no trimestre")
    with patch("fluxo_financeiro.graph.graph.yfinance_agent", _agente("Dados para VALE3.SA: P/L 74.7x")), \
         patch("fluxo_financeiro.graph.graph.detectar_sinais_anomalia", return_value=[sinal]), \
         patch("fluxo_financeiro.graph.graph.indicadores_economicos_em_texto", return_value="INDICADORES ECONÔMICOS"):
        resultado = yfinance_node({"messages": [PEDIDO]})

    assert resultado["dados_mercado"] == resultado["messages"][0].content
    assert "SINAIS DE ANOMALIA" in resultado["dados_mercado"]
    assert "prejuízo no trimestre" in resultado["dados_mercado"]


def test_analyzer_primeira_passagem_grava_noticias():
    """Confere que a primeira passagem do Analyzer grava em noticias e não toca em contexto_setor."""
    resultado = _rodar_analyzer({"messages": [PEDIDO], "dados_mercado": "dados"})

    assert resultado["noticias"] == "análise de notícias"
    assert "contexto_setor" not in resultado


def test_analyzer_segunda_grava_contexto_setor():
    """Confere que, com noticias já preenchido, o Analyzer grava em contexto_setor."""
    resultado = _rodar_analyzer({"messages": [PEDIDO], "noticias": "notícias da empresa"}, "contexto do setor")

    assert resultado["contexto_setor"] == "contexto do setor"
    assert "noticias" not in resultado


def test_analyzer_terceira_nao_sobrescreve_noticias():
    """Confere que uma terceira passagem do Analyzer vai para contexto_setor e deixa noticias como estava."""
    state = {"messages": [PEDIDO], "noticias": "notícias da empresa", "contexto_setor": "setor antigo"}

    resultado = _rodar_analyzer(state, "mais contexto")

    assert "noticias" not in resultado
    assert resultado["contexto_setor"] == "mais contexto"


def test_investigator_grava_diagnostico():
    """Confere que o Investigator grava a resposta em diagnostico."""
    with patch("fluxo_financeiro.graph.graph.investigator_agent", _agente("- Causa identificada: impairment")):
        resultado = investigator_node({"messages": [PEDIDO]})

    assert resultado["diagnostico"] == "- Causa identificada: impairment"
    assert resultado["messages"][0].name == "Investigator"


def test_no_grava_campo_mesmo_com_erro():
    """Confere que uma resposta de erro ou vazia também é gravada, e a passagem seguinte vai para contexto_setor."""
    erro = _rodar_analyzer({"messages": [PEDIDO]}, "Erro ao buscar notícias: 429")
    assert erro["noticias"] == "Erro ao buscar notícias: 429"

    vazia = _rodar_analyzer({"messages": [PEDIDO]}, "")
    assert vazia["noticias"] == ""

    seguinte = _rodar_analyzer({"messages": [PEDIDO], "noticias": ""}, "contexto do setor")
    assert seguinte["contexto_setor"] == "contexto do setor"
    assert "noticias" not in seguinte
