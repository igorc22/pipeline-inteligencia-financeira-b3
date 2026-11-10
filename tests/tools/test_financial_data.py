from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import pandas as pd
import pytest
import requests
from fluxo_financeiro.tools.brapi import ParesDoSetor, PerfilBrapi
from fluxo_financeiro.tools.financial_data import (
    AVISO_PERFIL_RESERVA,
    buscar_dados_acao_b3,
    busca_indicador_bcb,
    calcular_metricas_risco,
    calcular_piotroski_score,
    indicadores_economicos_em_texto,
)
from tests.tools.yahoo_falso import com_moeda


@pytest.fixture(autouse=True)
def brapi():
    """Brapi sem resposta por padrão (os testes de antes valem como o caminho da reserva); cada teste pode trocar."""
    with patch('fluxo_financeiro.tools.financial_data.buscar_perfil', return_value=None) as perfil, \
         patch('fluxo_financeiro.tools.financial_data.buscar_pares_do_setor', return_value=None) as pares:
        yield SimpleNamespace(perfil=perfil, pares=pares)


# ---------------------------------------------------------------------------
# buscar_dados_acao_b3
# ---------------------------------------------------------------------------

PERFIL_WEGE3 = PerfilBrapi(
    nome="WEG SA",
    preco=48.19,
    variacao_pct=-0.23,
    minima_52s=41.15,
    maxima_52s=54.53,
    valor_mercado=210010383322,
    lpa=1.4940624,
    setor="Bens Industriais",
    subsetor="Máquinas e Equipamentos",
    sumario="A WEG fabrica motores elétricos.",
)

PARES_WEGE3 = ParesDoSetor(
    setor="Producer Manufacturing",
    posicao=1,
    total=36,
    pares=[
        ("WEGE3", "WEG S.A.", 210010383322),
        ("FRAS3", "FRASLE MOBILITY S.A.", 5.9e9),
        ("SHUL4", "SCHULZ S.A.", 1.2e9),
    ],
)


# P/L do yfinance coerente com preço / LPA da Brapi (48,19 / 1,494 = 32,3), como na WEGE3 real
INFO_WEGE3 = {
    'currentPrice': 48.19, 'trailingPE': 32.3, 'returnOnEquity': 0.30, 'dividendYield': 0.02,
    'industry': 'Electrical Equipment', 'longBusinessSummary': 'WEG makes motors.',
}


def _acao_yf(mock_ticker, info=None):
    """Ação falsa do yfinance com 5 fechamentos e o info pedido."""
    mock_instance = MagicMock()
    mock_ticker.return_value = mock_instance
    mock_instance.history.return_value = pd.DataFrame(
        {'Close': [38.0, 38.5, 39.0, 39.5, 40.0]},
        index=pd.date_range('2024-01-01', periods=5)
    )
    mock_instance.info = info if info is not None else {
        'currentPrice': 40.0, 'trailingPE': 5.2, 'returnOnEquity': 0.18, 'dividendYield': 0.06,
        'industry': 'Oil & Gas', 'longBusinessSummary': 'Petrobras explora petróleo.',
    }
    return mock_instance


@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_dados_b3_usa_cotacao_e_perfil_da_brapi(mock_ticker, brapi):
    """Confere que, com a Brapi respondendo, nome, cotação, setor e sumário vêm dela e o P/L continua do yfinance."""
    _acao_yf(mock_ticker)
    brapi.perfil.return_value = PERFIL_WEGE3

    result = buscar_dados_acao_b3.invoke("WEGE3")

    assert "Dados para WEGE3.SA:" in result
    assert "Empresa: WEG SA" in result
    assert "Preço Atual: R$ 48,19 (no dia: -0,23%)" in result
    assert "Faixa de 52 semanas: R$ 41,15 a R$ 54,53" in result
    assert "P/L:  5,2x" in result
    assert "Setor: Bens Industriais | Subsetor: Máquinas e Equipamentos" in result
    assert "Industria:" not in result
    assert '<conteudo_externo origem="brapi">' in result
    assert "A WEG fabrica motores elétricos." in result
    assert "Fonte: cotação e perfil da Brapi" in result
    assert AVISO_PERFIL_RESERVA not in result


@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_dados_b3_normaliza_ticker_para_brapi(mock_ticker, brapi):
    """Confere que ticker minúsculo e com .sa chega à Brapi como PETR4 e ao yfinance como PETR4.SA."""
    _acao_yf(mock_ticker)

    result = buscar_dados_acao_b3.invoke("petr4.sa")

    brapi.perfil.assert_called_once_with("PETR4")
    mock_ticker.assert_called_once_with("PETR4.SA")
    assert "Dados para PETR4.SA:" in result


@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_dados_b3_perfil_sem_setor_cai_no_yfinance(mock_ticker, brapi):
    """Confere que, sem summaryProfile na Brapi, setor e sumário vêm do yfinance e o nome e a cotação da Brapi."""
    _acao_yf(mock_ticker)
    brapi.perfil.return_value = PerfilBrapi(
        nome="PETROBRAS", preco=38.5, variacao_pct=None, minima_52s=None, maxima_52s=None,
        valor_mercado=None, lpa=None, setor=None, subsetor=None, sumario=None,
    )

    result = buscar_dados_acao_b3.invoke("PETR4")

    assert "Empresa: PETROBRAS" in result
    assert "Preço Atual: R$ 38,50\n" in result
    assert "Faixa de 52 semanas" not in result
    assert "Industria: Oil & Gas" in result
    assert '<conteudo_externo origem="yfinance">' in result
    assert "Fonte: cotação e perfil da Brapi" in result


@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_dados_b3_sem_brapi_avisa_reserva(mock_ticker, brapi):
    """Confere que, sem a Brapi, a saída é a do yfinance e termina com o aviso da reserva."""
    _acao_yf(mock_ticker)

    result = buscar_dados_acao_b3.invoke("PETR4")

    assert result.rstrip().endswith(AVISO_PERFIL_RESERVA)
    assert "Preço Atual: R$ 40,00\n" in result
    assert "Empresa:" not in result
    assert "Fonte: cotação e perfil da Brapi" not in result
    brapi.pares.assert_not_called()


@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_dados_b3_valor_de_mercado_e_lpa(mock_ticker, brapi):
    """Confere as linhas de valor de mercado e LPA, que somem quando a Brapi não traz os dois."""
    _acao_yf(mock_ticker, info=INFO_WEGE3)
    brapi.perfil.return_value = PERFIL_WEGE3

    result = buscar_dados_acao_b3.invoke("WEGE3")
    assert "Valor de mercado: R$ 210,0 bi" in result
    assert "LPA: R$ 1,49" in result

    brapi.perfil.return_value = PerfilBrapi(**{**PERFIL_WEGE3.__dict__, "valor_mercado": None, "lpa": None})
    result = buscar_dados_acao_b3.invoke("WEGE3")
    assert "Valor de mercado" not in result
    assert "LPA" not in result


@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_dados_b3_lpa_some_quando_nao_bate_com_o_pl(mock_ticker, brapi):
    """Confere que o LPA da Brapi some quando preço / LPA não bate com o P/L do yfinance (caso real da VALE3)."""
    _acao_yf(mock_ticker, info={**INFO_WEGE3, 'trailingPE': 77.16})
    brapi.perfil.return_value = PerfilBrapi(**{**PERFIL_WEGE3.__dict__, "preco": 64.04, "lpa": 0.5177})

    result = buscar_dados_acao_b3.invoke("VALE3")

    assert "LPA" not in result
    assert "P/L:  77,2x" in result


@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_dados_b3_pares_do_setor(mock_ticker, brapi):
    """Confere o bloco dos maiores do setor, com a posição da empresa, e que ele some sem os pares."""
    _acao_yf(mock_ticker)
    brapi.perfil.return_value = PERFIL_WEGE3
    brapi.pares.return_value = PARES_WEGE3

    result = buscar_dados_acao_b3.invoke("WEGE3")
    brapi.pares.assert_called_once_with("WEGE3")
    assert "Maiores do setor na Brapi (Producer Manufacturing, por valor de mercado): WEGE3 é a 1ª de 36." in result
    assert "  1. WEGE3 WEG S.A.: R$ 210,0 bi" in result
    assert "2. FRAS3 FRASLE MOBILITY S.A.: R$ 5,9 bi" in result

    brapi.pares.return_value = None
    result = buscar_dados_acao_b3.invoke("WEGE3")
    assert "Maiores do setor" not in result


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

@pytest.mark.parametrize("serie, nome, unidade", [
    (432, "SELIC_META", "% a.a."),
    (4389, "CDI", "% a.a."),  # a série anualizada: a 12 é o CDI diário e saía como "0,05% a.a."
    (13522, "IPCA_12M", "% em 12 meses"),
])
@patch('fluxo_financeiro.tools.financial_data.requests.get')
def test_busca_indicador_bcb(mock_get, serie, nome, unidade):
    """Confere que cada série pede a URL dela, com o timeout de 5 s, e volta com nome, valor, data e unidade."""
    mock_get.return_value.json.return_value = [{'valor': '13.65', 'data': '05/11/2026'}]

    result = busca_indicador_bcb.invoke({'input_data': {'indicador': serie}})

    assert f'bcdata.sgs.{serie}/' in mock_get.call_args.args[0]
    assert mock_get.call_args.kwargs['timeout'] == 5
    assert result == {'indicador': nome, 'valor': 13.65, 'data': '05/11/2026', 'unidade': unidade}


@patch('fluxo_financeiro.tools.financial_data.requests.get')
def test_bcb_repete_json_invalido(mock_get, espera_falsa):
    """Confere que a resposta que não é JSON (caso real do BCB) é pedida de novo e a segunda vale."""
    quebrada = MagicMock()
    quebrada.json.side_effect = requests.JSONDecodeError("Expecting value", "<html>", 0)
    certa = MagicMock()
    certa.json.return_value = [{'valor': '13.65', 'data': '05/11/2026'}]
    mock_get.side_effect = [quebrada, certa]

    result = busca_indicador_bcb.invoke({'input_data': {'indicador': 4389}})

    assert mock_get.call_count == 2
    espera_falsa.assert_called_once_with(2.0)
    assert result['valor'] == 13.65 and 'error' not in result


@patch('fluxo_financeiro.tools.financial_data.requests.get')
def test_bcb_pede_dois_valores_e_fica_com_o_mais_recente(mock_get):
    """Confere que a consulta pede os 2 últimos valores (o ultimos/1 da série 4389 devolvia 304 vazio) e usa o de data mais nova, em qualquer ordem."""
    for ordem in ([{'valor': '13.65', 'data': '05/11/2026'}, {'valor': '13.40', 'data': '04/11/2026'}],
                  [{'valor': '13.40', 'data': '04/11/2026'}, {'valor': '13.65', 'data': '05/11/2026'}]):
        mock_get.return_value.json.return_value = ordem

        result = busca_indicador_bcb.invoke({'input_data': {'indicador': 4389}})

        assert "/ultimos/2?" in mock_get.call_args.args[0]
        assert result['valor'] == 13.65 and result['data'] == '05/11/2026'


@patch('fluxo_financeiro.tools.financial_data.requests.get')
def test_bcb_timeout_duas_vezes_devolve_erro(mock_get, espera_falsa):
    """Confere que o timeout repetido do BCB é pedido 2 vezes e depois vira o dict com 'error', sem levantar."""
    mock_get.side_effect = requests.Timeout('lento')

    result = busca_indicador_bcb.invoke({'input_data': {'indicador': 432}})

    assert 'error' in result
    assert mock_get.call_count == 2
    espera_falsa.assert_called_once_with(2.0)


# ---------------------------------------------------------------------------
# indicadores_economicos_em_texto
# ---------------------------------------------------------------------------

RESPOSTAS_BCB = {
    432: {'valor': '13.75', 'data': '08/12/2026'},  # meta vigente com data à frente de hoje, como o BCB manda
    4389: {'valor': '13.65', 'data': '05/11/2026'},
    13522: {'valor': '4.58', 'data': '01/09/2026'},
}


def _bcb_falso(falhas=()):
    """requests.get falso que responde pela série da URL; as séries em `falhas` levantam."""
    def responder(url, timeout=None):
        serie = int(url.split('bcdata.sgs.')[1].split('/')[0])
        if serie in falhas:
            raise TimeoutError(f"série {serie} fora do ar")
        resposta = MagicMock()
        resposta.json.return_value = [RESPOSTAS_BCB[serie]]
        return resposta
    return responder


@patch('fluxo_financeiro.tools.financial_data.requests.get')
def test_indicadores_em_texto_tres_series(mock_get):
    """Confere o bloco com SELIC, CDI e IPCA de 12 meses, com a data da SELIC à frente de hoje como veio."""
    mock_get.side_effect = _bcb_falso()

    assert indicadores_economicos_em_texto() == (
        "INDICADORES ECONÔMICOS (Banco Central, buscados em código):\n"
        "- SELIC (meta): 13,75% a.a. (BCB, 08/12/2026)\n"
        "- CDI: 13,65% a.a. (BCB, 05/11/2026)\n"
        "- IPCA acumulado em 12 meses: 4,58% (BCB, 01/09/2026)"
    )


@patch('fluxo_financeiro.tools.financial_data.requests.get')
def test_indicadores_em_texto_uma_falha(mock_get):
    """Confere que a série que falha some do bloco e as outras continuam."""
    mock_get.side_effect = _bcb_falso(falhas={4389})

    texto = indicadores_economicos_em_texto()

    assert "CDI" not in texto
    assert "- SELIC (meta): 13,75% a.a. (BCB, 08/12/2026)" in texto
    assert "- IPCA acumulado em 12 meses: 4,58% (BCB, 01/09/2026)" in texto


@patch('fluxo_financeiro.tools.financial_data.requests.get')
def test_indicadores_em_texto_tudo_falha(mock_get):
    """Confere que, com o BCB fora do ar, o bloco vem vazio e nada levanta."""
    mock_get.side_effect = _bcb_falso(falhas={432, 4389, 13522})

    assert indicadores_economicos_em_texto() == ""


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
    """Confere que calcular_metricas_risco traz as seis métricas, com a SELIC buscada no BCB."""
    mock_response = MagicMock()
    mock_response.json.return_value = [{'valor': '13.25', 'data': '09/05/2026'}]
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
    assert "13,25%" in result


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
    assert "10,75%" in result  # valor fallback


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

    assert "Net Income positivo (US$ 0,80 bi)" in result
    assert "Operating Cash Flow positivo (US$ 1,00 bi)" in result
    assert "Net Income diminuiu (US$ 0,80 bi vs US$ 1,00 bi)" in result
    assert "R$" not in result.replace("US$", "")


@patch('fluxo_financeiro.tools.financial_data.yf.Ticker')
def test_calcular_piotroski_com_moeda_falhando(mock_ticker):
    """Confere que falha ao buscar a moeda não vira erro: o score sai, sem símbolo de moeda."""
    mock_ticker.return_value = _acao_piotroski(Exception("timeout"))

    result = calcular_piotroski_score.invoke("VALE3")

    assert "Piotroski F-Score" in result
    assert "Erro" not in result
    assert "$" not in result
