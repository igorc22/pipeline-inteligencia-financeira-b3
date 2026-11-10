"""Detecção de anomalias em código, sem LLM. Usada pelo nó do YFinance para alimentar o guard do Investigator.

Não é uma @tool: nenhum agente decide chamá-la. O grafo chama sempre, depois da coleta de dados,
e o resultado decide de forma determinística se o Investigator roda já na Etapa 2, em paralelo com o Analyzer.

Regras (calibradas em 02/11/2026 com VALE3, WEGE3, PETR4, ITUB4, MGLU3, BBAS3, ABEV3):
- queda_lucro: lucro líquido do último trimestre caiu mais de QUEDA_LUCRO_LIMITE em relação ao
  mesmo trimestre do ano anterior. Comparar com o mesmo trimestre (e não com o anterior) evita
  confundir sazonalidade com problema: muita empresa vende mais em certos trimestres todo ano.
- prejuizo: o último trimestre fechou com lucro líquido negativo.
- piotroski_fraco: Piotroski F-Score anual <= PIOTROSKI_FRACO (faixa "fraca" do projeto).
Quando o yfinance não traz o dado (trimestre faltando, NaN), a regra é pulada, nunca acusa.
Os valores saem na moeda dos demonstrativos (financialCurrency), que pode não ser o real.
"""
import math
from dataclasses import dataclass
from typing import Any

import yfinance as yf

from fluxo_financeiro.shared.retry import com_retentativas
from fluxo_financeiro.shared.types import SinalAnomalia
from fluxo_financeiro.shared.utils import logger, numero_br
from fluxo_financeiro.tools.financial_data import _calcular_score
from fluxo_financeiro.tools.moeda import com_simbolo, ler_simbolo_moeda

QUEDA_LUCRO_LIMITE = 0.30
PIOTROSKI_FRACO = 3
TRIMESTRES_NUM_ANO = 4


def detectar_sinais_anomalia(ticker: str) -> list[SinalAnomalia]:
    """Calcula os sinais de anomalia do ticker. Nunca levanta exceção: em erro, devolve []."""
    if not ticker.endswith(".SA"):
        ticker += ".SA"
    logger.info(f"[anomalias] detectando sinais para {ticker}")
    try:
        # Retry local: a leitura do yfinance repete uma vez em timeout ou conexão caída.
        dados = com_retentativas(lambda: _ler_dados(ticker), contexto=f"[anomalias] {ticker}")
        sinais = _sinais_trimestrais(ticker, dados.trimestral, dados.simbolo)
        sinais += _sinal_piotroski(ticker, dados)
    except Exception:
        logger.exception(f"[anomalias] falha ao detectar sinais de {ticker}; seguindo sem sinais")
        return []
    logger.info(f"[anomalias] {ticker}: {[s.tipo for s in sinais] or 'nenhum sinal'}")
    return sinais


@dataclass(frozen=True)
class _DadosYahoo:
    simbolo: str
    trimestral: Any
    financials: Any
    balance_sheet: Any
    cashflow: Any


def _ler_dados(ticker: str) -> _DadosYahoo:
    """Tudo o que o detector lê do yfinance, de uma vez (as propriedades do yfinance só buscam quando lidas).

    Fica numa função só para o retry repetir a leitura inteira.
    """
    acao = yf.Ticker(ticker)
    return _DadosYahoo(
        simbolo=ler_simbolo_moeda(acao, ticker),
        trimestral=acao.quarterly_financials,
        financials=acao.financials,
        balance_sheet=acao.balance_sheet,
        cashflow=acao.cashflow,
    )


def _valido(valor) -> bool:
    return valor is not None and not (isinstance(valor, float) and math.isnan(valor))


def _bilhoes(valor: float, simbolo: str) -> str:
    """Valor em bilhões no formato brasileiro (vírgula decimal): o texto vai direto para o relatório."""
    return com_simbolo(f"{numero_br(valor / 1e9)} bi", simbolo)


def _sinais_trimestrais(ticker, trimestral, simbolo="") -> list[SinalAnomalia]:
    if trimestral is None or trimestral.empty or "Net Income" not in trimestral.index:
        return []
    lucro = trimestral.sort_index(axis=1, ascending=False).loc["Net Income"]
    if not _valido(lucro.iloc[0]):
        return []

    atual, data = float(lucro.iloc[0]), lucro.index[0].strftime("%d/%m/%Y")
    sinais = []
    if atual < 0:
        sinais.append(SinalAnomalia(
            tipo="prejuizo",
            descricao=f"{ticker} teve prejuízo líquido de {_bilhoes(abs(atual), simbolo)} no trimestre encerrado em {data}.",
        ))

    if len(lucro) > TRIMESTRES_NUM_ANO and _valido(lucro.iloc[TRIMESTRES_NUM_ANO]):
        ano_anterior = float(lucro.iloc[TRIMESTRES_NUM_ANO])
        if ano_anterior > 0:
            variacao = (atual - ano_anterior) / ano_anterior
            if variacao < -QUEDA_LUCRO_LIMITE:
                sinais.append(SinalAnomalia(
                    tipo="queda_lucro",
                    descricao=(
                        f"O lucro líquido de {ticker} no trimestre encerrado em {data} caiu {abs(variacao):.0%} "
                        f"em relação ao mesmo trimestre do ano anterior "
                        f"({_bilhoes(atual, simbolo)} contra {_bilhoes(ano_anterior, simbolo)})."
                    ),
                ))
    return sinais


def _sinal_piotroski(ticker, dados: _DadosYahoo) -> list[SinalAnomalia]:
    demonstrativo, balanco, fluxo = dados.financials, dados.balance_sheet, dados.cashflow
    if demonstrativo.empty or balanco.empty or fluxo.empty:
        return []
    score = _calcular_score(demonstrativo, balanco, fluxo)["piotroski_score"]
    if score > PIOTROSKI_FRACO:
        return []
    return [SinalAnomalia(
        tipo="piotroski_fraco",
        descricao=f"{ticker} tem Piotroski F-Score {score}/9 (faixa fraca, 0 a {PIOTROSKI_FRACO}): fundamentos frágeis no último ano.",
    )]
