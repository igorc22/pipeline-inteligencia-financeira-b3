import anthropic
import pandas as pd
import yfinance as yf
from langchain_core.tools import tool

from fluxo_financeiro.shared.config import MODEL
from fluxo_financeiro.shared.utils import logger


@tool
def buscar_historico_trimestral(ticker: str) -> str:
    """
    Retorna histórico de resultados trimestrais de uma ação da B3 (últimos 8 trimestres).
    Inclui Net Income, Receita Total e Lucro Bruto por trimestre via yfinance.
    Use para detectar se queda de lucro é pontual (evento isolado) ou estrutural
    (padrão recorrente de vários trimestres consecutivos).
    Compare Q atual com Qs anteriores para identificar a anomalia no histórico.
    Ticker sem sufixo é aceito (ex: VALE3) — o .SA é adicionado automaticamente.
    """
    if not ticker.endswith('.SA'):
        ticker += '.SA'

    logger.info(f"[tool] buscar_historico_trimestral: ticker={ticker}")
    try:
        acao = yf.Ticker(ticker)
        df = acao.quarterly_financials

        if df is None or df.empty:
            logger.warning(f"[tool] buscar_historico_trimestral: sem dados para {ticker}")
            return f"Dados trimestrais não encontrados para {ticker}."

        df = df.sort_index(axis=1, ascending=False)
        n_trimestres = 8
        colunas = df.columns[:n_trimestres]

        linhas_interesse = ['Net Income', 'Total Revenue', 'Gross Profit']
        df_filtrado = df.loc[df.index.isin(linhas_interesse), colunas]

        resultado = f"Histórico Trimestral de {ticker} (últimos {len(colunas)} trimestres):\n\n"
        resultado += f"{'Métrica':<20}"
        for col in colunas:
            resultado += f"{str(col.date()):<14}"
        resultado += "\n" + "-" * (20 + 14 * len(colunas)) + "\n"

        for linha in linhas_interesse:
            if linha in df_filtrado.index:
                resultado += f"{linha:<20}"
                for col in colunas:
                    val = df_filtrado.loc[linha, col]
                    resultado += f"{val/1e9:>10.2f}B  " if not pd.isna(val) else f"{'N/A':>10}   "
                resultado += "\n"

        logger.info(f"[tool] buscar_historico_trimestral: ok — {len(colunas)} trimestres")
        return resultado

    except Exception as e:
        logger.exception(f"[tool] buscar_historico_trimestral falhou para {ticker}")
        return f"Erro ao buscar histórico trimestral de {ticker}: {e}"


@tool
def buscar_fatos_relevantes(ticker: str) -> str:
    """
    Busca fatos relevantes e eventos corporativos formais de uma empresa da B3 via web search.
    Inclui: impairments, reestruturações, provisões, eventos extraordinários.
    Use quando um número financeiro parece atípico e você precisa identificar
    se houve evento corporativo específico que justifique o resultado fora do padrão.
    Usa Anthropic Web Search para resultados em tempo real.
    Ticker sem sufixo é aceito (ex: VALE3) — o .SA é adicionado automaticamente.
    """
    if not ticker.endswith('.SA'):
        ticker += '.SA'

    ticker_base = ticker.replace('.SA', '')
    logger.info(f"[tool] buscar_fatos_relevantes: ticker={ticker_base}")

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[{
                'role': 'user',
                'content': (
                    f'Busque fatos relevantes, impairments, reestruturações e eventos '
                    f'corporativos extraordinários de {ticker_base} nos últimos 6 meses. '
                    f'Foque em eventos que expliquem variações atípicas nos resultados '
                    f'financeiros. Seja conciso (max 3 parágrafos).'
                )
            }],
            tools=[{'type': 'web_search_20250305', 'name': 'web_search'}]
        )
        textos = [block.text for block in response.content if block.type == 'text']
        if not textos:
            logger.warning(f"[tool] buscar_fatos_relevantes: nenhum resultado para {ticker_base}")
            return f'Nenhum fato relevante encontrado para: {ticker_base}'
        logger.info(f"[tool] buscar_fatos_relevantes: ok ({len(textos)} blocos de texto)")
        return f'Fatos relevantes e eventos corporativos de {ticker_base}:\n\n' + '\n'.join(textos)

    except Exception as e:
        logger.exception(f"[tool] buscar_fatos_relevantes falhou para {ticker_base}")
        return f"Erro ao buscar fatos relevantes para {ticker_base}: {e}"
