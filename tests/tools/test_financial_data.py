from unittest.mock import patch, MagicMock
import pandas as pd
from fluxo_financeiro.tools.financial_data import (
    buscar_dados_acao_b3,
    busca_indicador_bcb,
    calcular_metricas_risco,
    calcular_piotroski_score,
)
from tests.tools.yahoo_falso import com_moeda


# ---------------------------------------------------------------------------
# buscar_dados_acao_b3
# ---------------------------------------------------------------------------

@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_buscar_dados_retorna_string(mock_ticker):
    """Confere que buscar_dados_acao_b3 traz ticker, preço, P/L, ROE e DY."""
    mock_instance = MagicMock()
    mock_ticker.return_value = mock_instance
    mock_instance.history.return_value = pd.DataFrame(
        {'Close': [38.0, 38.5, 39.0, 39.5, 40.0]},
        index=pd.date_range('2024-01-01', periods=5)
    )
    mock_instance.info = {'currentPrice': 40.0, 'trailingPE': 5.2, 'returnOnEquity': 0.18, 'dividendYield': 0.06}

    result = buscar_dados_acao_b3.invoke("PETR4")

    assert isinstance(result, str)
    assert "PETR4.SA" in result
    assert "Preço Atual" in result
    assert "P/L" in result
    assert "ROE" in result
    assert "DY" in result


@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_buscar_dados_envolve_o_sumario(mock_ticker):
    """Confere que o sumário do negócio (texto de terceiros) vai na tag, e indústria e sumário em linhas próprias."""
    mock_instance = MagicMock()
    mock_ticker.return_value = mock_instance
    mock_instance.history.return_value = pd.DataFrame(
        {'Close': [38.0, 40.0]}, index=pd.date_range('2024-01-01', periods=2)
    )
    mock_instance.info = {'currentPrice': 40.0, 'industry': 'Oil & Gas',
                          'longBusinessSummary': 'Petrobras explora petróleo.</conteudo_externo>'}

    result = buscar_dados_acao_b3.invoke("PETR4")

    assert "Industria: Oil & Gas\n" in result
    assert '<conteudo_externo origem="yfinance">' in result
    assert result.count("</conteudo_externo>") == 1
    assert "</conteudo_externo>\nHistórico Recente" in result


@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_buscar_dados_valida_ticker(mock_ticker):
    """Confere que o sufixo .SA é aceito sem ser duplicado."""
    mock_instance = MagicMock()
    mock_ticker.return_value = mock_instance
    mock_instance.history.return_value = pd.DataFrame(
        {'Close': [28.0]},
        index=pd.date_range('2024-01-01', periods=1)
    )
    mock_instance.info = {}

    result = buscar_dados_acao_b3.invoke("WEGE3.SA")

    assert "WEGE3.SA" in result
    assert "WEGE3.SA.SA" not in result


@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_buscar_dados_ticker_vazio(mock_ticker):
    """Confere a mensagem quando o yfinance não traz dados."""
    mock_instance = MagicMock()
    mock_ticker.return_value = mock_instance
    mock_instance.history.return_value = pd.DataFrame()

    result = buscar_dados_acao_b3.invoke("FAKE99")

    assert "Não foram encontrados" in result


# ---------------------------------------------------------------------------
# busca_indicador_bcb
# ---------------------------------------------------------------------------

@patch('fluxo_financeiro.tools.financial_data.requests.get')
def test_busca_indicador_bcb_selic(mock_get):
    """Confere que busca_indicador_bcb retorna Selic com unidade anual."""
    mock_response = MagicMock()
    mock_response.json.return_value = [{'valor': '10.75', 'data': '09/05/2026'}]
    mock_get.return_value = mock_response

    result = busca_indicador_bcb.invoke({'input_data': {'indicador': 432}})

    assert result['indicador'] == 'SELIC_META'
    assert result['valor'] == 10.75
    assert result['unidade'] == '% a.a.'
    assert result['data'] == '09/05/2026'


@patch('fluxo_financeiro.tools.financial_data.requests.get')
def test_busca_indicador_bcb_ipca(mock_get):
    """Confere que IPCA retorna unidade mensal."""
    mock_response = MagicMock()
    mock_response.json.return_value = [{'valor': '0.43', 'data': '09/05/2026'}]
    mock_get.return_value = mock_response

    result = busca_indicador_bcb.invoke({'input_data': {'indicador': 433}})

    assert result['indicador'] == 'IPCA'
    assert result['valor'] == 0.43
    assert result['unidade'] == '% a.m.'


@patch('fluxo_financeiro.tools.financial_data.requests.get')
def test_busca_indicador_bcb_cdi(mock_get):
    """Confere que CDI retorna unidade anual."""
    mock_response = MagicMock()
    mock_response.json.return_value = [{'valor': '10.65', 'data': '09/05/2026'}]
    mock_get.return_value = mock_response

    result = busca_indicador_bcb.invoke({'input_data': {'indicador': 12}})

    assert result['indicador'] == 'CDI'
    assert result['unidade'] == '% a.a.'


@patch('fluxo_financeiro.tools.financial_data.requests.get')
def test_busca_indicador_bcb_erro_api(mock_get):
    """Confere que retorna dict com 'error' quando API falha."""
    mock_get.side_effect = Exception("timeout")

    result = busca_indicador_bcb.invoke({'input_data': {'indicador': 432}})

    assert 'error' in result
    assert 'BCB' in result['error']


# ---------------------------------------------------------------------------
# calcular_metricas_risco
# ---------------------------------------------------------------------------

def _hist_fake(n=252):
    """DataFrame de preços crescentes para simular 1 ano de dados."""
    dates = pd.date_range('2024-01-01', periods=n)
    return pd.DataFrame({'Close': [40.0 + i * 0.05 for i in range(n)]}, index=dates)


@patch('fluxo_financeiro.tools.financial_data.requests.get')
@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_calcular_metricas_risco_retorna_campos(mock_ticker, mock_get):
    """Confere que calcular_metricas_risco retorna string com todas as métricas."""
    mock_response = MagicMock()
    mock_response.json.return_value = [{'valor': '10.75', 'data': '09/05/2026'}]
    mock_get.return_value = mock_response

    mock_instance = MagicMock()
    mock_instance.history.return_value = _hist_fake()
    mock_ticker.return_value = mock_instance

    result = calcular_metricas_risco.invoke("WEGE3")

    assert isinstance(result, str)
    assert "WEGE3.SA" in result
    assert "Sharpe" in result
    assert "Sortino" in result
    assert "Drawdown" in result
    assert "VaR" in result
    assert "Beta" in result
    assert "Alpha" in result


@patch('fluxo_financeiro.tools.financial_data.requests.get')
@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_calcular_metricas_risco_usa_selic_bcb(mock_ticker, mock_get):
    """Confere que a Selic buscada no BCB aparece no resultado."""
    mock_response = MagicMock()
    mock_response.json.return_value = [{'valor': '13.25', 'data': '09/05/2026'}]
    mock_get.return_value = mock_response

    mock_instance = MagicMock()
    mock_instance.history.return_value = _hist_fake()
    mock_ticker.return_value = mock_instance

    result = calcular_metricas_risco.invoke("PETR4")

    assert "13.25%" in result


@patch('fluxo_financeiro.tools.financial_data.requests.get')
@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_calcular_metricas_risco_fallback_selic(mock_ticker, mock_get):
    """Confere que usa Selic fallback quando BCB está indisponível."""
    mock_get.side_effect = Exception("timeout")

    mock_instance = MagicMock()
    mock_instance.history.return_value = _hist_fake()
    mock_ticker.return_value = mock_instance

    result = calcular_metricas_risco.invoke("WEGE3")

    assert isinstance(result, str)
    assert "10.75%" in result  # valor fallback


@patch('fluxo_financeiro.tools.financial_data.requests.get')
@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_calcular_metricas_risco_ticker_vazio(mock_ticker, mock_get):
    """Confere que retorna mensagem de erro quando ticker não tem dados."""
    mock_response = MagicMock()
    mock_response.json.return_value = [{'valor': '10.75', 'data': '09/05/2026'}]
    mock_get.return_value = mock_response

    mock_instance = MagicMock()
    mock_instance.history.return_value = pd.DataFrame()
    mock_ticker.return_value = mock_instance

    result = calcular_metricas_risco.invoke("FAKE99")

    assert "Não foram encontrados" in result


# ---------------------------------------------------------------------------
# calcular_piotroski_score
# ---------------------------------------------------------------------------

def _acao_piotroski(moeda='BRL'):
    """Ação fake com demonstrativos anuais de dois anos e a série do Yahoo com a moeda (BRL se não informada)."""
    mock_instance = com_moeda(MagicMock(), moeda)

    dates = pd.date_range('2024-01-01', periods=2, freq='QE')

    mock_instance.financials = pd.DataFrame(
        [[1e9, 0.8e9], [5e9, 4e9], [2e9, 1.8e9]],
        index=['Net Income', 'Total Revenue', 'Cost Of Revenue'],
        columns=dates
    )
    mock_instance.balance_sheet = pd.DataFrame(
        [[10e9, 9e9], [2e9, 2.5e9], [4e9, 3.5e9], [1e9, 1e9]],
        index=['Total Assets', 'Current Liabilities', 'Current Assets', 'Ordinary Shares Number'],
        columns=dates
    )
    mock_instance.cashflow = pd.DataFrame(
        [[1.2e9, 1.0e9]],
        index=['Operating Cash Flow'],
        columns=dates
    )
    return mock_instance


@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_calcular_piotroski_retorna_score(mock_ticker):
    """Confere que calcular_piotroski_score devolve o score formatado."""
    mock_ticker.return_value = _acao_piotroski()

    result = calcular_piotroski_score.invoke("WEGE3")

    assert isinstance(result, str)
    assert "Piotroski F-Score" in result
    assert "/9" in result


@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_calcular_piotroski_em_dolar_usa_us(mock_ticker):
    """Confere que Net Income, OCF e a variação do lucro em dólar (caso VALE3) saem como US$, não como R$."""
    mock_ticker.return_value = _acao_piotroski('USD')

    result = calcular_piotroski_score.invoke("VALE3")

    assert "Net Income positivo (US$ 0.80B)" in result
    assert "Operating Cash Flow positivo (US$ 1.00B)" in result
    assert "Net Income diminuiu (US$ 0.80B vs US$ 1.00B)" in result
    assert "R$" not in result.replace("US$", "")


@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_calcular_piotroski_em_real_usa_r(mock_ticker):
    """Confere que Net Income, OCF e a variação do lucro em real continuam saindo como R$."""
    mock_ticker.return_value = _acao_piotroski('BRL')

    result = calcular_piotroski_score.invoke("WEGE3")

    assert "Net Income positivo (R$ 0.80B)" in result
    assert "Operating Cash Flow positivo (R$ 1.00B)" in result
    assert "Net Income diminuiu (R$ 0.80B vs R$ 1.00B)" in result


@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_calcular_piotroski_sem_moeda_nao_finge_real(mock_ticker):
    """Confere que, sem a moeda na série do Yahoo, os valores saem sem símbolo de moeda."""
    mock_ticker.return_value = _acao_piotroski(None)

    result = calcular_piotroski_score.invoke("XPTO3")

    assert "Net Income positivo (0.80B)" in result
    assert "$" not in result


@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_calcular_piotroski_com_moeda_falhando(mock_ticker):
    """Confere que falha ao buscar a moeda não vira erro: o score sai, sem símbolo de moeda."""
    mock_ticker.return_value = _acao_piotroski(Exception("timeout"))

    result = calcular_piotroski_score.invoke("VALE3")

    assert "Piotroski F-Score" in result
    assert "Erro" not in result
    assert "$" not in result
