"""Respostas falsas do Yahoo para os testes que leem a moeda dos demonstrativos (tools/moeda.py)."""
import json


def serie_yahoo(*moedas):
    """Resposta do fundamentals-timeseries com um lucro trimestral por moeda (do mais antigo ao mais novo)."""
    itens = [
        {"asOfDate": f"2026-0{i + 1}-30", "currencyCode": m, "reportedValue": {"raw": 1e9, "fmt": "1.00B"}}
        for i, m in enumerate(moedas)
    ]
    return {"timeseries": {"result": [{"meta": {}, "timestamp": [], "quarterlyNetIncome": itens}]}}


def com_moeda(acao, moeda):
    """Faz o `_data.cache_get` do `yf.Ticker` falso devolver a série na `moeda` (None: série sem moeda;
    exceção: a busca falha)."""
    if isinstance(moeda, Exception):
        acao._data.cache_get.side_effect = moeda
    else:
        payload = serie_yahoo(moeda) if moeda else {}
        acao._data.cache_get.return_value.text = json.dumps(payload)
    return acao
