from unittest.mock import patch, MagicMock
import pandas as pd
from fluxo_financeiro.tools.investigation import buscar_historico_trimestral, buscar_fatos_relevantes


# ---------------------------------------------------------------------------
# buscar_historico_trimestral
# ---------------------------------------------------------------------------

def _df_trimestral_fake(n=4):
    dates = pd.date_range('2024-01-01', periods=n, freq='QE')
    return pd.DataFrame(
        [[1e9] * n, [10e9] * n, [3e9] * n],
        index=['Net Income', 'Total Revenue', 'Gross Profit'],
        columns=dates
    )


@patch('fluxo_financeiro.tools.investigation.yf.Ticker')
def test_buscar_historico_trimestral_retorna_string(mock_ticker):
    """Test que retorna string formatada com métricas trimestrais."""
    mock_instance = MagicMock()
    mock_ticker.return_value = mock_instance
    mock_instance.quarterly_financials = _df_trimestral_fake()

    result = buscar_historico_trimestral.invoke("VALE3")

    assert isinstance(result, str)
    assert "VALE3.SA" in result
    assert "Net Income" in result
    assert "Total Revenue" in result


@patch('fluxo_financeiro.tools.investigation.yf.Ticker')
def test_buscar_historico_trimestral_adiciona_sa(mock_ticker):
    """Test que .SA é adicionado automaticamente ao ticker."""
    mock_instance = MagicMock()
    mock_ticker.return_value = mock_instance
    mock_instance.quarterly_financials = _df_trimestral_fake()

    buscar_historico_trimestral.invoke("VALE3")

    mock_ticker.assert_called_once_with("VALE3.SA")


@patch('fluxo_financeiro.tools.investigation.yf.Ticker')
def test_buscar_historico_trimestral_sem_dados(mock_ticker):
    """Test que retorna mensagem amigável quando yfinance não tem dados."""
    mock_instance = MagicMock()
    mock_ticker.return_value = mock_instance
    mock_instance.quarterly_financials = pd.DataFrame()

    result = buscar_historico_trimestral.invoke("FAKE99")

    assert "não encontrados" in result.lower() or "não encontrado" in result.lower()


@patch('fluxo_financeiro.tools.investigation.yf.Ticker')
def test_buscar_historico_trimestral_erro_yfinance(mock_ticker):
    """Test que captura exceção do yfinance e retorna string de erro."""
    mock_ticker.side_effect = Exception("network error")

    result = buscar_historico_trimestral.invoke("VALE3")

    assert "Erro" in result


# ---------------------------------------------------------------------------
# buscar_fatos_relevantes
# ---------------------------------------------------------------------------

@patch('fluxo_financeiro.tools.investigation.anthropic.Anthropic')
def test_buscar_fatos_relevantes_retorna_conteudo(mock_anthropic_class):
    """Test que retorna conteúdo quando web search encontra resultados."""
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client

    mock_block = MagicMock()
    mock_block.type = 'text'
    mock_block.text = 'Vale registra impairment de R$4B em ativos de níquel.'
    mock_client.messages.create.return_value.content = [mock_block]

    result = buscar_fatos_relevantes.invoke("VALE3")

    assert isinstance(result, str)
    assert "Vale registra impairment" in result


@patch('fluxo_financeiro.tools.investigation.anthropic.Anthropic')
def test_buscar_fatos_relevantes_sem_resultados(mock_anthropic_class):
    """Test que retorna mensagem amigável quando web search não retorna texto."""
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    mock_client.messages.create.return_value.content = []

    result = buscar_fatos_relevantes.invoke("DESCONHECIDO")

    assert "Nenhum" in result or "nenhum" in result


@patch('fluxo_financeiro.tools.investigation.anthropic.Anthropic')
def test_buscar_fatos_relevantes_erro_api(mock_anthropic_class):
    """Test que captura exceção e retorna string de erro."""
    mock_anthropic_class.side_effect = Exception("API timeout")

    result = buscar_fatos_relevantes.invoke("VALE3")

    assert "Erro" in result
