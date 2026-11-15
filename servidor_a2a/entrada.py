"""Entrada do servidor A2A: o texto da mensagem vira um ticker aceito ou um motivo de recusa.

Mesma regra das outras entradas (CLI, dashboard, e2e): ticker no formato da B3 e, se a Brapi
responder 404, recusa com sugestão. Diferente da CLI, aqui a mensagem é texto livre de outro
agente, então um ticker dentro de uma frase também serve, e dois tickers são recusados.
"""
from dataclasses import dataclass

from fluxo_financeiro.shared.utils import TICKER_INVALIDO, extrair_tickers, validar_ticker

VARIOS_TICKERS = "Envie um ticker por mensagem: encontrei {tickers}."


@dataclass(frozen=True)
class Entrada:
    """Resultado da leitura: ou um ticker aceito, ou o motivo da recusa (nunca os dois)."""

    ticker: str | None
    recusa: str | None


def resolver_entrada(texto: str) -> Entrada:
    """Ticker normalizado (sem .SA) do texto da mensagem, ou a recusa que o agente devolve ao cliente."""
    # Importado aqui para o patch no módulo de origem valer nos testes.
    from fluxo_financeiro.tools.brapi import mensagem_ticker_inexistente, ticker_existe

    ticker = validar_ticker(texto)
    if ticker is None:
        tickers = extrair_tickers(texto or "")
        if not tickers:
            return Entrada(ticker=None, recusa=TICKER_INVALIDO)
        if len(tickers) > 1:
            return Entrada(ticker=None, recusa=VARIOS_TICKERS.format(tickers=", ".join(tickers)))
        ticker = tickers[0]

    # None (Brapi sem resposta: cota, timeout, sem token) segue, como na CLI.
    if ticker_existe(ticker) is False:
        return Entrada(ticker=None, recusa=mensagem_ticker_inexistente(ticker))
    return Entrada(ticker=ticker, recusa=None)
