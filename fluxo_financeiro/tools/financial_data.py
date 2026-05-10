import yfinance as yf
import requests
import numpy as np
import pandas as pd
from langchain_core.tools import tool
from fluxo_financeiro.shared.types import ConsultaBCBInput
from fluxo_financeiro.shared.utils import logger
from typing import Any, Dict

@tool
def buscar_dados_acao_b3(ticker: str) -> str:
    """
    Busca dados de mercado atuais de uma ação da B3 via yfinance.
    Retorna: preço atual (R$), P/L (Price/Earnings), ROE (Return on Equity),
    DY (Dividend Yield) e histórico dos últimos 5 dias de fechamento.
    Use para responder perguntas sobre preço, valuation básico e tendência recente.
    Ticker sem sufixo é aceito (ex: PETR4) — o .SA é adicionado automaticamente.
    """
    if not ticker.endswith('.SA'):
        ticker += '.SA'

    logger.info(f"[tool] buscar_dados_acao_b3: ticker={ticker}")
    try:
        acao = yf.Ticker(ticker)
        hist = acao.history(period="6mo")
        if hist.empty:
            logger.warning(f"[tool] buscar_dados_acao_b3: sem dados para {ticker}")
            return f"Não foram encontrados dados para o ticker {ticker}."

        info = acao.info
        preco_atual = info.get('currentPrice', hist['Close'].iloc[-1])
        pl  = info.get('trailingPE')
        roe = info.get('returnOnEquity')
        dy  = info.get('dividendYield')
        industria = info.get('industry')
        sumario = info.get('longBusinessSummary')
        # yfinance às vezes retorna DY já como percentual (ex: 0.88 = 88% em vez de 0.88%)
        if dy and dy > 0.20:
            dy = dy / 100

        resultado = f"Dados para {ticker}:\n"
        resultado += f"Preço Atual: R$ {preco_atual}\n"
        resultado += f"P/L:  {f'{pl:.1f}x' if pl else 'N/A'}\n"
        resultado += f"ROE:  {f'{roe*100:.1f}%' if roe else 'N/A'}\n"
        resultado += f"DY:   {f'{dy*100:.2f}%' if dy else 'N/A'}\n"
        resultado += f"Industria: {industria}"
        resultado += f"Sumario de Negócio: {sumario}"
        resultado += f"Histórico Recente (Últimos 5 dias de fechamento):\n{hist['Close'].tail(5).to_string()}\n"
        logger.info(f"[tool] buscar_dados_acao_b3: ok ({len(resultado)} chars)")
        return resultado
    except Exception as e:
        logger.exception(f"[tool] buscar_dados_acao_b3 falhou para {ticker}")
        return f"Erro ao buscar dados do ticker {ticker}: {e}"

@tool
def busca_indicador_bcb(input_data: ConsultaBCBInput) -> Dict[str, Any]:
    """
    Consulta a API do Banco Central (SGS) para obter o valor mais recente
    de indicadores macroeconômicos brasileiros.
    Retorna: nome do indicador, valor numérico, data de referência e unidade.
    Use para obter a taxa Selic vigente (432), variação mensal do IPCA (433)
    ou taxa CDI (12) — especialmente quando precisar de benchmarks para
    calcular Sharpe Ratio, retorno real ou comparar com renda fixa.
    """
    codigo = input_data.indicador.value

    # Unidades por série SGS: Selic e CDI são anualizados (% a.a.), IPCA é mensal (% a.m.)
    unidades = {432: "% a.a.", 433: "% a.m.", 12: "% a.a."}
    unidade = unidades.get(codigo, "%")

    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados/ultimos/1?formato=json"

    logger.info(f"[tool] busca_indicador_bcb: indicador={input_data.indicador.name}")
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        dados = response.json()[0]

        valor = float(dados["valor"])
        logger.info(f"[tool] busca_indicador_bcb: ok — {input_data.indicador.name}={valor}{unidade}")
        return {
            "indicador": input_data.indicador.name,
            "valor": valor,
            "data": dados["data"],
            "unidade": unidade,
        }
    except Exception as e:
        logger.exception(f"[tool] busca_indicador_bcb falhou para {input_data.indicador.name}")
        return {"error": f"Erro ao acessar o BCB: {str(e)}"}

@tool
def calcular_metricas_risco(ticker: str) -> str:
    """
    Calcula 6 métricas de risco para uma ação da B3 usando dados do último 1 ano.
    Métricas: Sharpe Ratio, Sortino Ratio, Maximum Drawdown, VaR 95% (Monte Carlo),
    Beta e Alpha (CAPM vs IBOV). Usa Selic 10.75% a.a. como taxa livre de risco.
    Use quando precisar avaliar o perfil de risco/retorno de uma ação: se ela é defensiva
    ou agressiva, se compensou o risco em relação à Selic, e qual a pior queda histórica.
    Ticker sem sufixo é aceito (ex: PETR4) — o .SA é adicionado automaticamente.
    """
    if not ticker.endswith('.SA'):
        ticker += '.SA'

    logger.info(f"[tool] calcular_metricas_risco: ticker={ticker}")
    BENCHMARK = '^BVSP'

    # Busca Selic atual do BCB (série SGS 432); fallback se API indisponível
    try:
        resp = requests.get(
            "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json",
            timeout=5,
        )
        SELIC_ANUAL = float(resp.json()[0]["valor"]) / 100
    except Exception:
        logger.warning(f"[tool] calcular_metricas_risco: BCB indisponivel — usando Selic fallback 10.75%")
        SELIC_ANUAL = 0.1075

    try:
        hist = yf.Ticker(ticker).history(period='1y')
        hist_ibov = yf.Ticker(BENCHMARK).history(period='1y')

        if hist.empty:
            logger.warning(f"[tool] calcular_metricas_risco: sem dados para {ticker}")
            return f"Não foram encontrados dados para {ticker}."

        retornos = hist['Close'].pct_change().dropna()
        retornos_ibov = hist_ibov['Close'].pct_change().dropna()

        df = pd.DataFrame({'acao': retornos, 'ibov': retornos_ibov}).dropna()

        if len(df) < 30:
            logger.warning(f"[tool] calcular_metricas_risco: dados insuficientes para {ticker} ({len(df)} dias)")
            return f"Dados insuficientes para calcular métricas de {ticker}."

        selic_diaria = (1 + SELIC_ANUAL) ** (1/252) - 1
        retorno_medio = df['acao'].mean()
        volatilidade = df['acao'].std()

        # Sharpe
        sharpe = (retorno_medio - selic_diaria) / volatilidade * np.sqrt(252)

        # Sortino (penaliza só quedas)
        downside_std = df['acao'][df['acao'] < 0].std()
        sortino = (retorno_medio - selic_diaria) / downside_std * np.sqrt(252)

        # Maximum Drawdown
        pico = hist['Close'].cummax()
        mdd = ((hist['Close'] - pico) / pico).min()

        # VaR 95% Monte Carlo
        np.random.seed(42)
        simulacoes = np.random.normal(retorno_medio, volatilidade, 10_000)
        var_95 = np.percentile(simulacoes, 5)

        # Beta e Alpha (CAPM)
        cov_matrix = df.cov()
        beta = cov_matrix.loc['acao', 'ibov'] / df['ibov'].var()
        retorno_anual = (1 + retorno_medio) ** 252 - 1
        retorno_anual_ibov = (1 + df['ibov'].mean()) ** 252 - 1
        retorno_esperado = SELIC_ANUAL + beta * (retorno_anual_ibov - SELIC_ANUAL)
        alpha = retorno_anual - retorno_esperado

        def _label_sharpe(v):
            return 'Bom' if v > 1.0 else 'OK' if v >= 0.5 else 'Fraco'

        def _label_beta(v):
            return 'agressivo' if v > 1.2 else 'defensivo' if v < 0.8 else 'neutro'

        resultado = f"Métricas de Risco para {ticker} (último 1 ano):\n"
        resultado += f"Referência: Selic {SELIC_ANUAL:.2%} a.a. (BCB), benchmark IBOV\n\n"
        resultado += f"Sharpe Ratio:      {sharpe:.2f} ({_label_sharpe(sharpe)})\n"
        resultado += f"Sortino Ratio:     {sortino:.2f}\n"
        resultado += f"Max Drawdown:      {mdd:.1%}\n"
        resultado += f"VaR 95% (diário):  {var_95:.2%}\n"
        resultado += f"Beta (vs IBOV):    {beta:.2f} ({_label_beta(beta)})\n"
        resultado += f"Alpha (anual):     {alpha:.1%} ({'acima' if alpha > 0 else 'abaixo'} do esperado pelo CAPM)\n"
        logger.info(f"[tool] calcular_metricas_risco: ok — Sharpe={sharpe:.2f}")
        return resultado

    except Exception as e:
        logger.exception(f"[tool] calcular_metricas_risco falhou para {ticker}")
        return f"Erro ao calcular métricas de risco para {ticker}: {e}"


def _calcular_score(df_demonstrativo, df_balanco, df_fluxo_caixa) -> dict:
    """Implementa os 9 critérios do Piotroski F-Score com dados anuais do yfinance."""
    score = 0
    details = {}

    fin = df_demonstrativo.sort_index(axis=1, ascending=False)
    bs  = df_balanco.sort_index(axis=1, ascending=False)
    cf  = df_fluxo_caixa.sort_index(axis=1, ascending=False)

    cur_fin = fin.iloc[:, 0]
    prv_fin = fin.iloc[:, 1] if fin.shape[1] > 1 else fin.iloc[:, 0]
    cur_bs  = bs.iloc[:, 0]
    prv_bs  = bs.iloc[:, 1] if bs.shape[1] > 1 else bs.iloc[:, 0]
    cur_cf  = cf.iloc[:, 0]

    ni  = cur_fin.get('Net Income', 0)
    ocf = cur_cf.get('Operating Cash Flow', 0)
    prv_ni = prv_fin.get('Net Income', 0)

    # 1. Net Income > 0
    if ni > 0:
        score += 1
        details['net_income'] = f"[OK] Net Income positivo (R$ {ni/1e9:.2f}B)"
    else:
        details['net_income'] = f"[NAO] Net Income negativo (R$ {ni/1e9:.2f}B)"

    # 2. OCF > 0
    if ocf > 0:
        score += 1
        details['ocf'] = f"[OK] Operating Cash Flow positivo (R$ {ocf/1e9:.2f}B)"
    else:
        details['ocf'] = f"[NAO] Operating Cash Flow negativo (R$ {ocf/1e9:.2f}B)"

    # 3. Net Income crescente
    if ni > prv_ni:
        score += 1
        details['ni_growth'] = f"[OK] Net Income cresceu ({ni/1e9:.2f}B vs {prv_ni/1e9:.2f}B)"
    else:
        details['ni_growth'] = f"[NAO] Net Income diminuiu ({ni/1e9:.2f}B vs {prv_ni/1e9:.2f}B)"

    # 4. Qualidade do lucro: OCF > NI
    if ocf > ni:
        score += 1
        details['cash_quality'] = f"[OK] OCF > Net Income — lucro com qualidade de caixa"
    else:
        details['cash_quality'] = f"[NAO] OCF <= Net Income — lucro pode ser inflado"

    # 5. Total Assets crescente
    cur_assets = cur_bs.get('Total Assets', 0)
    prv_assets = prv_bs.get('Total Assets', 0)
    if cur_assets > 0 and prv_assets > 0:
        if cur_assets > prv_assets:
            score += 1
            details['assets'] = f"[OK] Total Assets cresceu (+{(cur_assets/prv_assets-1)*100:.1f}%)"
        else:
            details['assets'] = f"[NAO] Total Assets diminuiu ({(cur_assets/prv_assets-1)*100:.1f}%)"
    else:
        details['assets'] = "[ALERTA] Dados de Total Assets incompletos"

    # 6. Redução de Current Liabilities
    cur_liab = cur_bs.get('Current Liabilities', 0)
    prv_liab = prv_bs.get('Current Liabilities', 0)
    if cur_liab > 0 and prv_liab > 0:
        if cur_liab < prv_liab:
            score += 1
            details['debt'] = f"[OK] Divida corrente reduziu ({(1-cur_liab/prv_liab)*100:.1f}%)"
        else:
            details['debt'] = f"[NAO] Divida corrente aumentou (+{(cur_liab/prv_liab-1)*100:.1f}%)"
    else:
        details['debt'] = "[ALERTA] Dados de Current Liabilities incompletos"

    # 7. Current Ratio melhorou
    cur_ca = cur_bs.get('Current Assets', 0)
    prv_ca = prv_bs.get('Current Assets', 0)
    if cur_ca > 0 and cur_liab > 0 and prv_ca > 0 and prv_liab > 0:
        cr_cur = cur_ca / cur_liab
        cr_prv = prv_ca / prv_liab
        if cr_cur > cr_prv:
            score += 1
            details['liquidity'] = f"[OK] Current Ratio melhorou ({cr_cur:.2f} vs {cr_prv:.2f})"
        else:
            details['liquidity'] = f"[NAO] Current Ratio piorou ({cr_cur:.2f} vs {cr_prv:.2f})"
    else:
        details['liquidity'] = "[ALERTA] Dados para Current Ratio incompletos"

    # 8. Sem diluição de ações
    cur_shares = cur_bs.get('Ordinary Shares Number', 0)
    prv_shares = prv_bs.get('Ordinary Shares Number', 0)
    if cur_shares > 0 and prv_shares > 0:
        if cur_shares <= prv_shares:
            score += 1
            details['shares'] = f"[OK] Sem diluicao de acoes"
        else:
            details['shares'] = f"[NAO] Diluicao detectada (+{(cur_shares/prv_shares-1)*100:.1f}% novas acoes)"
    else:
        details['shares'] = "[ALERTA] Dados de shares ordinarias indisponíveis"

    # 9. Gross Margin melhorou
    cur_rev  = cur_fin.get('Total Revenue', 1) or 1
    cur_cogs = cur_fin.get('Cost Of Revenue', 0)
    prv_rev  = prv_fin.get('Total Revenue', 1) or 1
    prv_cogs = prv_fin.get('Cost Of Revenue', 0)
    gm_cur = (cur_rev - cur_cogs) / cur_rev
    gm_prv = (prv_rev - prv_cogs) / prv_rev
    if gm_cur > gm_prv:
        score += 1
        details['margin'] = f"[OK] Gross Margin melhorou ({gm_cur:.1%} vs {gm_prv:.1%})"
    else:
        details['margin'] = f"[NAO] Gross Margin caiu ({gm_cur:.1%} vs {gm_prv:.1%})"

    if score >= 8:
        interpretation = 'Excelente (8-9) - Empresa com fundamentals muito solidos'
    elif score >= 6:
        interpretation = 'Bom (6-7) - Empresa competente, algumas fraquezas'
    else:
        interpretation = 'Fraco (0-5) - Empresa com serios problemas financeiros'

    return {'piotroski_score': score, 'interpretation': interpretation, 'details': details}


@tool
def calcular_piotroski_score(ticker: str) -> str:
    """
    Calcula o Piotroski F-Score (0-9) de uma ação da B3 usando dados anuais.
    Avalia 9 critérios em 3 dimensões: lucratividade (Net Income, OCF, crescimento),
    alavancagem (dívida, liquidez corrente) e eficiência (diluição de ações, margem bruta).
    Score 7-9 = excelente; 4-6 = bom; 0-3 = fraco.
    Use quando o pedido envolve análise fundamentalista ou solidez financeira da empresa.
    Ticker sem sufixo é aceito (ex: WEGE3) — o .SA é adicionado automaticamente.
    """
    if not ticker.endswith('.SA'):
        ticker += '.SA'

    logger.info(f"[tool] calcular_piotroski_score: ticker={ticker}")
    try:
        acao = yf.Ticker(ticker)
        df_demonstrativo = acao.financials
        df_balanco = acao.balance_sheet
        df_fluxo_caixa = acao.cashflow

        if df_demonstrativo.empty or df_balanco.empty or df_fluxo_caixa.empty:
            logger.warning(f"[tool] calcular_piotroski_score: dados insuficientes para {ticker}")
            return f"Dados financeiros insuficientes para calcular Piotroski de {ticker}."

        resultado = _calcular_score(df_demonstrativo, df_balanco, df_fluxo_caixa)

        score = resultado['piotroski_score']
        interpretation = resultado['interpretation']
        details = resultado['details']

        saida = f"Piotroski F-Score para {ticker}: {score}/9 — {interpretation}\n\n"
        saida += "Critérios:\n"
        for criterio, detalhe in details.items():
            saida += f"  {detalhe}\n"

        logger.info(f"[tool] calcular_piotroski_score: ok — score={score}/9")
        return saida
    except Exception as e:
        logger.exception(f"[tool] calcular_piotroski_score falhou para {ticker}")
        return f"Erro ao calcular Piotroski para {ticker}: {e}"
