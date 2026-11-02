import logging
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

@patch('fluxo_financeiro.tools.investigation.pesquisar_na_web')
def test_buscar_fatos_relevantes_retorna_conteudo(mock_pesquisa):
    """Test que retorna conteúdo quando a busca na web encontra resultados."""
    mock_pesquisa.return_value = 'Vale registra impairment de R$4B em ativos de níquel.\n\nFontes: valor.com.br'

    result = buscar_fatos_relevantes.invoke("VALE3")

    assert "Vale registra impairment" in result
    assert "Fontes:" in result
    assert "VALE3" in mock_pesquisa.call_args.args[0]  # ticker sem .SA no prompt


@patch('fluxo_financeiro.tools.investigation.pesquisar_na_web')
def test_buscar_fatos_relevantes_sem_resultados(mock_pesquisa):
    """Test que retorna mensagem amigável quando a busca não retorna texto."""
    mock_pesquisa.return_value = ""

    result = buscar_fatos_relevantes.invoke("DESCONHECIDO")

    assert "Nenhum fato relevante" in result


@patch('fluxo_financeiro.tools.investigation.pesquisar_na_web')
def test_buscar_fatos_relevantes_erro_api(mock_pesquisa):
    """Test que captura exceção e retorna string de erro."""
    mock_pesquisa.side_effect = Exception("API timeout")

    result = buscar_fatos_relevantes.invoke("VALE3")

    assert "Erro" in result


ERRO_GOOGLE = Exception("429 RESOURCE_EXHAUSTED.\n{'error': {'code': 429, 'details': [" + "x" * 2000 + "]}}")


@patch('fluxo_financeiro.tools.investigation.pesquisar_na_web')
def test_buscar_fatos_relevantes_erro_loga_uma_linha(mock_pesquisa, caplog):
    """Test que a falha da busca vira uma linha de ERROR, sem traceback e sem o JSON do SDK."""
    caplog.set_level(logging.INFO, logger="fluxo_financeiro")
    mock_pesquisa.side_effect = ERRO_GOOGLE

    buscar_fatos_relevantes.invoke("VALE3")

    erros = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(erros) == 1
    msg = erros[0].getMessage()
    assert "buscar_fatos_relevantes" in msg and "Exception: 429 RESOURCE_EXHAUSTED." in msg
    assert chr(10) not in msg and len(msg) < 400
    assert all(r.exc_info is None for r in caplog.records)
