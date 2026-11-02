from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from fluxo_financeiro.tools.anomalias import PIOTROSKI_FRACO, detectar_sinais_anomalia

NAN = float("nan")
NAO_VAZIO = pd.DataFrame({"x": [1.0]})


def _acao(lucros, piotroski=7):
    """Ação fake: `lucros` do trimestre mais recente para o mais antigo, em bilhões."""
    datas = pd.date_range(end="2026-06-30", periods=len(lucros), freq="QE")[::-1]
    acao = MagicMock()
    acao.quarterly_financials = pd.DataFrame([[v * 1e9 for v in lucros]], index=["Net Income"], columns=datas)
    acao.financials = acao.balance_sheet = acao.cashflow = NAO_VAZIO
    return acao, {"piotroski_score": piotroski, "interpretation": "", "details": {}}


@pytest.fixture
def mock_yf():
    with patch("fluxo_financeiro.tools.anomalias.yf.Ticker") as ticker, \
         patch("fluxo_financeiro.tools.anomalias._calcular_score") as score:
        def configurar(lucros, piotroski=7):
            acao, resultado = _acao(lucros, piotroski)
            ticker.return_value = acao
            score.return_value = resultado
        yield configurar


def _tipos(sinais):
    return sorted(s.tipo for s in sinais)


def test_queda_de_lucro_acima_do_limite(mock_yf):
    """Lucro 35% menor que o do mesmo trimestre do ano anterior → queda_lucro (caso VALE3)."""
    mock_yf([1.38, 1.5, 1.6, 1.7, 2.12, 2.0])

    sinais = detectar_sinais_anomalia("VALE3")

    assert _tipos(sinais) == ["queda_lucro"]
    assert "35%" in sinais[0].descricao and "VALE3.SA" in sinais[0].descricao


def test_queda_pequena_nao_acusa(mock_yf):
    """Queda de 14% (caso BBAS3) fica abaixo do limite de 30%."""
    mock_yf([2.40, 2.5, 2.6, 2.7, 2.78, 2.6])

    assert detectar_sinais_anomalia("BBAS3") == []


def test_alta_de_lucro_nao_acusa(mock_yf):
    """Lucro dobrando (caso PETR4) não é anomalia para o Investigator."""
    mock_yf([10.43, 8.0, 7.0, 6.0, 4.73, 5.0])

    assert detectar_sinais_anomalia("PETR4") == []


def test_prejuizo_no_trimestre(mock_yf):
    """Prejuízo quando o ano anterior também era prejuízo (caso MGLU3): só o sinal de prejuízo."""
    mock_yf([-0.07, -0.05, 0.01, -0.03, -0.02, 0.0])

    assert _tipos(detectar_sinais_anomalia("MGLU3")) == ["prejuizo"]


def test_lucro_que_virou_prejuizo_gera_os_dois_sinais(mock_yf):
    """Sair de lucro para prejuízo é queda de lucro e prejuízo ao mesmo tempo."""
    mock_yf([-1.0, 1.0, 1.0, 1.0, 2.0, 2.0])

    assert _tipos(detectar_sinais_anomalia("XPTO3")) == ["prejuizo", "queda_lucro"]


def test_ano_anterior_sem_dado_pula_a_regra(mock_yf):
    """yfinance com NaN no trimestre de comparação (caso ABEV3): a regra é pulada, não acusa."""
    mock_yf([4.25, 4.0, 3.9, 3.8, NAN, 3.5])

    assert detectar_sinais_anomalia("ABEV3") == []


def test_menos_de_cinco_trimestres_pula_a_regra(mock_yf):
    """Sem o mesmo trimestre do ano anterior não dá para comparar."""
    mock_yf([0.5, 2.0, 2.0, 2.0])

    assert detectar_sinais_anomalia("NOVA3") == []


def test_piotroski_fraco(mock_yf):
    """Piotroski na faixa fraca gera sinal, mesmo com lucro estável."""
    mock_yf([2.0, 2.0, 2.0, 2.0, 2.0, 2.0], piotroski=PIOTROSKI_FRACO)

    sinais = detectar_sinais_anomalia("FRAC3")

    assert _tipos(sinais) == ["piotroski_fraco"]
    assert f"{PIOTROSKI_FRACO}/9" in sinais[0].descricao


def test_erro_no_yfinance_devolve_lista_vazia():
    """Falha de rede ou ticker inexistente nunca derruba o fluxo: segue sem sinais."""
    with patch("fluxo_financeiro.tools.anomalias.yf.Ticker", side_effect=Exception("timeout")):
        assert detectar_sinais_anomalia("VALE3") == []
