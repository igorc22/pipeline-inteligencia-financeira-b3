"""Moeda dos demonstrativos financeiros do yfinance.

O yfinance devolve os demonstrativos na moeda em que a empresa publica, que nem sempre é o real:
a VALE3 publica em dólar. A cotação na B3 é sempre em reais, por isso o preço da ação não passa por aqui.

De onde vem a moeda: da série de demonstrativos do Yahoo (fundamentals-timeseries), em que cada valor
traz o `currencyCode`. O yfinance descarta esse campo ao montar o DataFrame, então a série é pedida de
novo pelo `_data.cache_get` do próprio `yf.Ticker` (API privada do yfinance, conferida na 1.3.0).
O `info["financialCurrency"]` não serve: em 07/11/2026 dizia BRL para a VALE3.SA, com a série em USD.
Qualquer falha aqui devolve "sem símbolo", nunca R$ por padrão.
"""
import datetime
import json

from fluxo_financeiro.shared.utils import logger

SIMBOLOS = {"BRL": "R$", "USD": "US$"}
SERIE_DA_MOEDA = "quarterlyNetIncome"
URL_SERIE = "https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{ticker}"


def simbolo_moeda(codigo) -> str:
    """Símbolo do código da moeda: BRL → R$, USD → US$, outro → o próprio código, ausente → ""."""
    if not isinstance(codigo, str) or not codigo.strip():
        return ""
    codigo = codigo.strip().upper()
    return SIMBOLOS.get(codigo, codigo)


def moeda_da_serie(dados) -> str | None:
    """`currencyCode` do valor mais recente da série de lucro trimestral do Yahoo, ou None."""
    try:
        resultados = dados["timeseries"]["result"]
        valores = next(r[SERIE_DA_MOEDA] for r in resultados if r.get(SERIE_DA_MOEDA))
        valores = [v for v in valores if isinstance(v, dict) and isinstance(v.get("currencyCode"), str)]
    except (KeyError, TypeError, AttributeError, StopIteration):
        return None
    if not valores:
        return None
    return max(valores, key=lambda v: str(v.get("asOfDate", "")))["currencyCode"]


def ler_simbolo_moeda(acao, ticker: str) -> str:
    """Símbolo da moeda dos demonstrativos do `yf.Ticker`. Nunca levanta exceção: em falha, devolve ""."""
    inicio = int(datetime.datetime(2016, 12, 31).timestamp())
    amanha = datetime.date.today() + datetime.timedelta(days=1)
    fim = int(datetime.datetime.combine(amanha, datetime.time()).timestamp())  # fixo no dia: o cache_get reaproveita
    url = URL_SERIE.format(ticker=ticker) + f"?symbol={ticker}&type={SERIE_DA_MOEDA}&period1={inicio}&period2={fim}"
    try:
        codigo = moeda_da_serie(json.loads(acao._data.cache_get(url=url).text))
    except Exception as e:
        logger.warning(f"[moeda] falha ao ler a moeda dos demonstrativos de {ticker}; valores sem símbolo: {e}")
        return ""
    if codigo is None:
        logger.warning(f"[moeda] {ticker}: série do Yahoo sem moeda; valores sem símbolo")
    return simbolo_moeda(codigo)


def com_simbolo(numero: str, simbolo: str) -> str:
    """Põe o símbolo na frente do número já formatado; sem símbolo, devolve só o número."""
    return f"{simbolo} {numero}" if simbolo else numero
