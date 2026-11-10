import json
from unittest.mock import MagicMock

import pytest

from fluxo_financeiro.tools.moeda import (
    com_simbolo,
    ler_simbolo_moeda,
    moeda_da_serie,
    simbolo_moeda,
)
from tests.tools.yahoo_falso import serie_yahoo


def acao_com_serie(payload, info=None):
    """`yf.Ticker` falso: o `_data.cache_get` devolve o `payload` em JSON (ou levanta, se for exceção)."""
    acao = MagicMock()
    acao.info = info if info is not None else {}
    if isinstance(payload, Exception):
        acao._data.cache_get.side_effect = payload
    else:
        acao._data.cache_get.return_value.text = json.dumps(payload)
    return acao


@pytest.mark.parametrize("codigo, esperado", [
    ("BRL", "R$"),
    ("USD", "US$"),
    ("EUR", "EUR"),
    (None, ""),
])
def test_simbolo_moeda(codigo, esperado):
    """Confere que o código da moeda vira símbolo e que moeda ausente não vira R$."""
    assert simbolo_moeda(codigo) == esperado


def test_com_simbolo():
    """Confere que o símbolo vai na frente do número e que, sem moeda, sai só o número."""
    assert com_simbolo("1.26 bi", "US$") == "US$ 1.26 bi"
    assert com_simbolo("1.26 bi", "") == "1.26 bi"


def test_moeda_da_serie_pega_o_valor_mais_recente():
    """Confere que a moeda vem do lucro mais recente da série (a empresa pode ter mudado de moeda)."""
    assert moeda_da_serie(serie_yahoo("BRL", "USD")) == "USD"


@pytest.mark.parametrize("payload", [
    {},
    {"timeseries": {"result": []}},
    {"timeseries": {"result": [{"quarterlyNetIncome": [None, {"asOfDate": "2026-09-30"}]}]}},
])
def test_moeda_da_serie_sem_moeda(payload):
    """Confere que série vazia, sem currencyCode ou em formato estranho devolve None, sem levantar."""
    assert moeda_da_serie(payload) is None


def test_ler_simbolo_moeda_usa_a_serie_e_nao_o_info():
    """Confere que vale a moeda da série (USD na VALE3) mesmo com o info dizendo BRL (o info do Yahoo erra a VALE3)."""
    acao = acao_com_serie(serie_yahoo("USD"), info={"financialCurrency": "BRL", "currency": "BRL"})

    assert ler_simbolo_moeda(acao, "VALE3.SA") == "US$"
    assert "VALE3.SA" in acao._data.cache_get.call_args.kwargs["url"]


def test_ler_simbolo_moeda_sem_moeda_na_serie():
    """Confere que, sem currencyCode na série, não há símbolo (não finge que é real)."""
    assert ler_simbolo_moeda(acao_com_serie({}), "XPTO3.SA") == ""


def test_ler_simbolo_moeda_com_falha_na_busca():
    """Confere que falha ao buscar a série não sobe: devolve sem símbolo."""
    assert ler_simbolo_moeda(acao_com_serie(Exception("timeout")), "VALE3.SA") == ""

