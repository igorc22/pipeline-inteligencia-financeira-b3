from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from fluxo_financeiro.tools.anomalias import PIOTROSKI_FRACO, detectar_sinais_anomalia
from tests.tools.yahoo_falso import com_moeda

NAN = float("nan")
NAO_VAZIO = pd.DataFrame({"x": [1.0]})


def _acao(lucros, piotroski=7, moeda="BRL"):
    """Ação fake: `lucros` do trimestre mais recente para o mais antigo, em bilhões."""
    datas = pd.date_range(end="2026-06-30", periods=len(lucros), freq="QE")[::-1]
    acao = MagicMock()
    com_moeda(acao, moeda)
    acao.quarterly_financials = pd.DataFrame([[v * 1e9 for v in lucros]], index=["Net Income"], columns=datas)
    acao.financials = acao.balance_sheet = acao.cashflow = NAO_VAZIO
    return acao, {"piotroski_score": piotroski, "interpretation": "", "details": {}}


@pytest.fixture
def mock_yf():
    with patch("fluxo_financeiro.tools.anomalias.yf.Ticker") as ticker, \
         patch("fluxo_financeiro.tools.anomalias._calcular_score") as score:
        def configurar(lucros, piotroski=7, moeda="BRL"):
            acao, resultado = _acao(lucros, piotroski, moeda)
            ticker.return_value = acao
            score.return_value = resultado
            return acao
        yield configurar


def _tipos(sinais):
    return sorted(s.tipo for s in sinais)


def test_queda_de_lucro_acima_do_limite(mock_yf):
    """Confere que lucro 35% menor que o do mesmo trimestre do ano anterior gera queda_lucro (caso VALE3)."""
    mock_yf([1.38, 1.5, 1.6, 1.7, 2.12, 2.0])

    sinais = detectar_sinais_anomalia("VALE3")

    assert _tipos(sinais) == ["queda_lucro"]
    assert "35%" in sinais[0].descricao and "VALE3.SA" in sinais[0].descricao


def test_queda_pequena_nao_acusa(mock_yf):
    """Confere que uma queda de 14% (caso BBAS3) fica abaixo do limite de 30%."""
    mock_yf([2.40, 2.5, 2.6, 2.7, 2.78, 2.6])

    assert detectar_sinais_anomalia("BBAS3") == []


def test_alta_de_lucro_nao_acusa(mock_yf):
    """Confere que lucro dobrando (caso PETR4) não é anomalia para o Investigator."""
    mock_yf([10.43, 8.0, 7.0, 6.0, 4.73, 5.0])

    assert detectar_sinais_anomalia("PETR4") == []


def test_prejuizo_no_trimestre(mock_yf):
    """Confere que prejuízo sobre prejuízo do ano anterior (caso MGLU3) gera só o sinal de prejuízo."""
    mock_yf([-0.07, -0.05, 0.01, -0.03, -0.02, 0.0])

    assert _tipos(detectar_sinais_anomalia("MGLU3")) == ["prejuizo"]


def test_lucro_que_virou_prejuizo_gera_os_dois_sinais(mock_yf):
    """Confere que sair de lucro para prejuízo gera queda de lucro e prejuízo ao mesmo tempo."""
    mock_yf([-1.0, 1.0, 1.0, 1.0, 2.0, 2.0])

    assert _tipos(detectar_sinais_anomalia("XPTO3")) == ["prejuizo", "queda_lucro"]


def test_ano_anterior_sem_dado_pula_a_regra(mock_yf):
    """Confere que, com NaN no trimestre de comparação (caso ABEV3), a regra é pulada e não acusa."""
    mock_yf([4.25, 4.0, 3.9, 3.8, NAN, 3.5])

    assert detectar_sinais_anomalia("ABEV3") == []


def test_menos_de_cinco_trimestres_pula_a_regra(mock_yf):
    """Confere que, sem o mesmo trimestre do ano anterior, a comparação não é feita."""
    mock_yf([0.5, 2.0, 2.0, 2.0])

    assert detectar_sinais_anomalia("NOVA3") == []


def test_piotroski_fraco(mock_yf):
    """Confere que Piotroski na faixa fraca gera sinal, mesmo com lucro estável."""
    mock_yf([2.0, 2.0, 2.0, 2.0, 2.0, 2.0], piotroski=PIOTROSKI_FRACO)

    sinais = detectar_sinais_anomalia("FRAC3")

    assert _tipos(sinais) == ["piotroski_fraco"]
    assert f"{PIOTROSKI_FRACO}/9" in sinais[0].descricao


def test_erro_no_yfinance_devolve_lista_vazia():
    """Confere que falha de rede ou ticker inexistente não derruba o fluxo: segue sem sinais."""
    with patch("fluxo_financeiro.tools.anomalias.yf.Ticker", side_effect=Exception("timeout")):
        assert detectar_sinais_anomalia("VALE3") == []


def test_anomalias_repete_e_depois_devolve_vazio(espera_falsa):
    """Confere que a falha temporária do yfinance é repetida uma vez e, falhando de novo, o resultado é [] como antes."""
    with patch("fluxo_financeiro.tools.anomalias.yf.Ticker", side_effect=TimeoutError("lento")) as ticker:
        assert detectar_sinais_anomalia("VALE3") == []

    assert ticker.call_count == 2
    espera_falsa.assert_called_once_with(2.0)


def test_anomalias_repete_e_acerta(mock_yf, espera_falsa):
    """Confere que, se a segunda leitura do yfinance dá certo, os sinais saem normalmente."""
    acao = mock_yf([1.26, 1.5, 1.6, 1.7, 2.69, 2.0])
    with patch("fluxo_financeiro.tools.anomalias.yf.Ticker", side_effect=[TimeoutError("lento"), acao]):
        sinais = detectar_sinais_anomalia("VALE3")

    assert _tipos(sinais) == ["queda_lucro"]
    espera_falsa.assert_called_once_with(2.0)


def test_queda_de_lucro_em_dolar_usa_us(mock_yf):
    """Confere que demonstrativo em dólar (caso VALE3) sai como US$, não como R$."""
    mock_yf([1.26, 1.5, 1.6, 1.7, 2.69, 2.0], moeda="USD")

    descricao = detectar_sinais_anomalia("VALE3")[0].descricao

    assert "US$ 1.26 bi contra US$ 2.69 bi" in descricao
    assert "R$" not in descricao.replace("US$", "")


def test_queda_de_lucro_em_real_usa_r(mock_yf):
    """Confere que demonstrativo em real continua saindo como R$."""
    mock_yf([1.38, 1.5, 1.6, 1.7, 2.12, 2.0], moeda="BRL")

    assert "R$ 1.38 bi contra R$ 2.12 bi" in detectar_sinais_anomalia("WEGE3")[0].descricao


def test_queda_de_lucro_sem_moeda_nao_finge_real(mock_yf):
    """Confere que, sem a moeda na série do Yahoo, sai só o número, sem símbolo de moeda."""
    mock_yf([1.38, 1.5, 1.6, 1.7, 2.12, 2.0], moeda=None)

    descricao = detectar_sinais_anomalia("XPTO3")[0].descricao

    assert "(1.38 bi contra 2.12 bi)" in descricao
    assert "$" not in descricao


def test_prejuizo_em_dolar_usa_us(mock_yf):
    """Confere que o prejuízo em dólar sai como US$."""
    mock_yf([-0.07, -0.05, 0.01, -0.03, -0.02, 0.0], moeda="USD")

    assert "prejuízo líquido de US$ 0.07 bi" in detectar_sinais_anomalia("XPTO3")[0].descricao


def test_falha_ao_ler_moeda_mantem_os_sinais(mock_yf):
    """Confere que falha ao buscar a moeda não apaga os sinais: eles saem sem símbolo."""
    mock_yf([1.38, 1.5, 1.6, 1.7, 2.12, 2.0], moeda=Exception("timeout"))

    sinais = detectar_sinais_anomalia("VALE3")

    assert _tipos(sinais) == ["queda_lucro"]
    assert "$" not in sinais[0].descricao
