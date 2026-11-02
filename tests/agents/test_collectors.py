from unittest.mock import patch, MagicMock
import pandas as pd
from fluxo_financeiro.agents.collectors import yfinance_agent
from fluxo_financeiro.tools.financial_data import (
    buscar_dados_acao_b3,
    calcular_metricas_risco,
    calcular_piotroski_score,
)

TOOLS_ESPERADAS = {'buscar_dados_acao_b3', 'calcular_metricas_risco', 'calcular_piotroski_score'}


# ---------------------------------------------------------------------------
# Estrutura do agent
# ---------------------------------------------------------------------------

def test_yfinance_agent_exists():
    """Test that yfinance_agent is properly initialized."""
    assert yfinance_agent is not None


def test_yfinance_agent_tools_tem_nomes_corretos():
    """Test que as tools têm os nomes que o LLM usa para chamá-las via tool-calling."""
    assert buscar_dados_acao_b3.name == 'buscar_dados_acao_b3'
    assert calcular_metricas_risco.name == 'calcular_metricas_risco'
    assert calcular_piotroski_score.name == 'calcular_piotroski_score'


def _tools_registradas(agent) -> dict:
    """Extrai o dict nome→tool do ToolNode interno do agent (PregelNode → ToolNode)."""
    tool_node = agent.nodes.get('tools')
    assert tool_node is not None, "Nó 'tools' não encontrado — agent pode estar mal configurado"
    return tool_node.node.steps[0].tools_by_name


def test_yfinance_agent_tem_3_tools():
    """Test que exatamente 3 tools estão registradas no nó tools do grafo."""
    assert len(_tools_registradas(yfinance_agent)) == 3


def test_yfinance_agent_tools_registradas_por_nome():
    """Test que as tools corretas estão vinculadas ao agent pelo nome exato."""
    assert set(_tools_registradas(yfinance_agent)) == TOOLS_ESPERADAS


# ---------------------------------------------------------------------------
# Invocação individual de cada tool (sem chamada real de API)
# ---------------------------------------------------------------------------

@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_buscar_dados_acao_b3_invocavel(mock_ticker):
    """Test que buscar_dados_acao_b3 retorna string com campos esperados."""
    mock_instance = MagicMock()
    mock_ticker.return_value = mock_instance
    mock_instance.history.return_value = pd.DataFrame(
        {'Close': [40.0, 40.5, 41.0, 41.5, 42.0]},
        index=pd.date_range('2024-01-01', periods=5)
    )
    mock_instance.info = {
        'currentPrice': 42.0,
        'trailingPE': 8.5,
        'returnOnEquity': 0.22,
        'dividendYield': 0.04,
    }

    result = buscar_dados_acao_b3.invoke("PETR4")

    assert isinstance(result, str)
    assert "PETR4.SA" in result
    assert "Preço Atual" in result
    assert "P/L" in result


@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
@patch('fluxo_financeiro.tools.financial_data.requests.get')
def test_calcular_metricas_risco_invocavel(mock_get, mock_ticker):
    """Test que calcular_metricas_risco retorna string com todas as métricas."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = [{'valor': '10.75', 'data': '09/05/2026'}]
    mock_get.return_value = mock_resp

    n = 252
    hist = pd.DataFrame(
        {'Close': [40.0 + i * 0.05 for i in range(n)]},
        index=pd.date_range('2024-01-01', periods=n),
    )
    mock_instance = MagicMock()
    mock_instance.history.return_value = hist
    mock_ticker.return_value = mock_instance

    result = calcular_metricas_risco.invoke("WEGE3")

    assert isinstance(result, str)
    assert "WEGE3.SA" in result
    assert "Sharpe" in result
    assert "Drawdown" in result
    assert "Beta" in result
    assert "10.75%" in result  # Selic buscada do BCB aparece no output


@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_calcular_piotroski_score_invocavel(mock_ticker):
    """Test que calcular_piotroski_score retorna string com score /9."""
    dates = pd.date_range('2024-01-01', periods=2, freq='QE')
    mock_instance = MagicMock()
    mock_ticker.return_value = mock_instance
    mock_instance.financials = pd.DataFrame(
        [[1e9, 0.8e9], [5e9, 4e9], [2e9, 1.8e9]],
        index=['Net Income', 'Total Revenue', 'Cost Of Revenue'],
        columns=dates,
    )
    mock_instance.balance_sheet = pd.DataFrame(
        [[10e9, 9e9], [2e9, 2.5e9], [4e9, 3.5e9], [1e9, 1e9]],
        index=['Total Assets', 'Current Liabilities', 'Current Assets', 'Ordinary Shares Number'],
        columns=dates,
    )
    mock_instance.cashflow = pd.DataFrame(
        [[1.2e9, 1.0e9]],
        index=['Operating Cash Flow'],
        columns=dates,
    )

    result = calcular_piotroski_score.invoke("WEGE3")

    assert isinstance(result, str)
    assert "Piotroski F-Score" in result
    assert "/9" in result
