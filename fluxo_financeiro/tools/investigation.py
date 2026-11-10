import pandas as pd
import yfinance as yf
from langchain_core.tools import tool

from fluxo_financeiro.shared.retry import com_retentativas
from fluxo_financeiro.shared.utils import logger
from fluxo_financeiro.tools.moeda import ler_simbolo_moeda
from fluxo_financeiro.tools.sanitizacao import tratar_conteudo_externo
from fluxo_financeiro.tools.web_search import buscar_na_web, origem_da_busca, registrar_falha_busca


@tool
def buscar_historico_trimestral(ticker: str) -> str:
    """
    Retorna histórico de resultados trimestrais de uma ação da B3 (últimos 8 trimestres).
    Inclui Net Income, Receita Total e Lucro Bruto por trimestre via yfinance.
    Use para detectar se queda de lucro é pontual (evento isolado) ou estrutural
    (padrão recorrente de vários trimestres consecutivos).
    Compare Q atual com Qs anteriores para identificar a anomalia no histórico.
    Ticker sem sufixo é aceito (ex: VALE3): o .SA é adicionado automaticamente.
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

        simbolo = ler_simbolo_moeda(acao, ticker)
        resultado = f"Histórico Trimestral de {ticker} (últimos {len(colunas)} trimestres):\n"
        resultado += (
            f"Valores em bilhões de {simbolo} (moeda dos demonstrativos).\n\n" if simbolo
            else "Valores em bilhões (moeda não informada pelo yfinance).\n\n"
        )
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

        logger.info(f"[tool] buscar_historico_trimestral: ok, {len(colunas)} trimestres")
        return resultado

    except Exception as e:
        logger.exception(f"[tool] buscar_historico_trimestral falhou para {ticker}")
        return f"Erro ao buscar histórico trimestral de {ticker}: {e}"


def pesquisar_pergunta(pergunta: str, ticker: str) -> str:
    """Uma busca na web para uma pergunta do subgrafo de pesquisa (agents/pesquisa.py), sem @tool.

    Quem chama é o código do subgrafo, não o LLM: por isso o erro temporário é repetido aqui
    (`com_retentativas`). Devolve o achado em <conteudo_externo> (com o classificador, se a flag
    estiver ligada). Busca sem texto ou erro que sobrou: "" e, no erro, uma linha de log. A pergunta
    fica sem achado e as outras seguem.
    """
    ticker_base = ticker.removesuffix('.SA')
    # A pergunta vem do LLM, que leu dados de fora: no prompt do Google, buscar_na_web a põe escapada
    # em <consulta>, como qualquer consulta (e a empresa em <empresa>). A Tavily recebe "empresa pergunta".
    instrucao = (
        "Responda à pergunta da consulta sobre a empresa da B3 indicada, buscando a causa de uma\n"
        "variação atípica nos resultados. Procure fatos relevantes, resultados trimestrais, impairments,\n"
        "preços de commodities e câmbio que expliquem o número, nos últimos 12 meses. Traga datas e\n"
        "números quando houver."
    )
    logger.info(f"[pesquisa] {ticker_base}: {pergunta[:80]}")
    try:
        resultado = com_retentativas(
            lambda: buscar_na_web(
                pergunta, instrucao, empresa=ticker_base, formato="Seja conciso: no máximo 2 parágrafos."
            ),
            contexto=f"[pesquisa] {ticker_base}",
        )
    except Exception as e:
        registrar_falha_busca(f"[pesquisa] busca falhou para {ticker_base}", e)
        return ""
    if not resultado:
        logger.warning(f"[pesquisa] {ticker_base}: busca sem resultado")
        return ""
    return tratar_conteudo_externo(resultado, origem_da_busca())
