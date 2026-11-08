"""Cliente da Brapi (brapi.dev), no que o plano gratuito libera.

No plano gratuito voltam a cotação, o summaryProfile (setor e subsetor da B3, sumário em português)
e a lista de papéis (/quote/list, com busca e filtro por setor). Os demonstrativos dão 403 fora dos
tickers de sandbox, então continuam no yfinance.

Nenhuma função daqui levanta exceção: Brapi fora do ar, sem token ou com cota estourada não derruba a
análise. Quem chama recebe None (não deu para saber) e segue com o yfinance. Só o 404 da conferência
do ticker diz "não existe". Todas recebem o ticker já normalizado (maiúsculas, sem .SA).
"""
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

import brapi

from fluxo_financeiro.shared.config import BRAPI_API_KEY
from fluxo_financeiro.shared.utils import SUGESTAO_TICKER, TICKER_NAO_ENCONTRADO, logger

TIMEOUT_SEGUNDOS = 10
# O SDK repete 2 vezes por padrão em timeout, 429 e 5xx: com a Brapi fora do ar, a entrada esperaria
# mais de 30 s antes de a análise começar, e no 429 as repetições gastariam a cota. Uma tentativa só:
# se falhar, o yfinance é a reserva.
MAX_RETENTATIVAS = 0
# A lista do setor vem paginada; 3 páginas de 100 cobrem os setores da B3 com folga.
MAX_PAGINAS_SETOR = 3
ITENS_POR_PAGINA = 100


@lru_cache(maxsize=1)
def criar_cliente() -> brapi.Brapi:
    """Cliente único da Brapi, criado na primeira chamada (importar o módulo não cria).

    Sem token, levanta: quem chama trata. A checagem é feita aqui porque o SDK, com api_key=None,
    procuraria o BRAPI_API_KEY no ambiente por conta própria.
    """
    if not BRAPI_API_KEY:
        raise brapi.BrapiError("BRAPI_API_KEY não configurada")
    return brapi.Brapi(api_key=BRAPI_API_KEY, timeout=TIMEOUT_SEGUNDOS, max_retries=MAX_RETENTATIVAS)


@dataclass(frozen=True)
class PerfilBrapi:
    nome: Optional[str]
    preco: Optional[float]
    variacao_pct: Optional[float]
    minima_52s: Optional[float]
    maxima_52s: Optional[float]
    valor_mercado: Optional[float]
    lpa: Optional[float]
    setor: Optional[str]
    subsetor: Optional[str]
    sumario: Optional[str]


@dataclass(frozen=True)
class ParesDoSetor:
    setor: str  # o nome do setor na lista da Brapi, em inglês (ex: "Producer Manufacturing")
    posicao: Optional[int]  # 1 = maior valor de mercado; None se a empresa não aparece na lista
    total: int
    pares: list[tuple[str, str, float]]  # (ticker, nome, valor de mercado), os maiores primeiro


def eh_papel_inteiro(codigo: str) -> bool:
    """True para o código de um papel inteiro (WEGE3, TAEE11); False para o fracionário (WEGE3F) e outros."""
    return re.fullmatch(r"[A-Z]{4}[0-9]{1,2}", codigo or "") is not None


def ticker_existe(ticker: str) -> Optional[bool]:
    """True se a Brapi devolve a cotação, False no 404, None se não deu para conferir (a análise segue)."""
    try:
        criar_cliente().quote.retrieve(tickers=ticker)
        return True
    except brapi.NotFoundError:
        return False
    except Exception as e:
        logger.warning(f"[brapi] não deu para conferir o ticker {ticker}: {type(e).__name__}")
        return None


def buscar_perfil(ticker: str) -> Optional[PerfilBrapi]:
    """Cotação e summaryProfile numa chamada só. None se a Brapi falhar ou não trouxer resultado."""
    try:
        resposta = criar_cliente().quote.retrieve(tickers=ticker, modules="summaryProfile")
        if not resposta.results:
            logger.warning(f"[brapi] perfil de {ticker}: resposta sem resultados")
            return None
        r = resposta.results[0]
        perfil = r.summary_profile
        return PerfilBrapi(
            nome=r.long_name,
            preco=r.regular_market_price,
            variacao_pct=r.regular_market_change_percent,
            minima_52s=r.fifty_two_week_low,
            maxima_52s=r.fifty_two_week_high,
            valor_mercado=r.market_cap,
            lpa=r.earnings_per_share,
            setor=perfil.sector if perfil else None,
            subsetor=perfil.industry if perfil else None,
            sumario=perfil.long_business_summary if perfil else None,
        )
    except Exception as e:
        logger.warning(f"[brapi] perfil de {ticker} indisponível: {type(e).__name__}")
        return None


def sugerir_ticker(ticker: str) -> Optional[str]:
    """Um papel inteiro com as mesmas 4 letras, diferente do digitado (WEGE4 → WEGE3). None se não houver."""
    try:
        resposta = criar_cliente().quote.list(search=ticker[:4])
        for item in resposta.stocks:
            if eh_papel_inteiro(item.stock) and item.stock != ticker:
                return item.stock
        return None
    except Exception as e:
        logger.warning(f"[brapi] sem sugestão para {ticker}: {type(e).__name__}")
        return None


def mensagem_ticker_inexistente(ticker: str) -> str:
    """Mensagem das entradas para o ticker que a Brapi diz não existir, com a sugestão quando há."""
    mensagem = TICKER_NAO_ENCONTRADO.format(ticker=ticker)
    sugestao = sugerir_ticker(ticker)
    if sugestao:
        mensagem += SUGESTAO_TICKER.format(sugestao=sugestao)
    return mensagem


def buscar_pares_do_setor(ticker: str, limite: int = 5) -> Optional[ParesDoSetor]:
    """Os maiores do setor da empresa por valor de mercado e a posição dela. None se não der.

    Fica um papel por empresa (o primeiro da lista, que já vem ordenada) e só papéis inteiros.
    """
    try:
        cliente = criar_cliente()
        busca = cliente.quote.list(search=ticker)
        proprio = next((item for item in busca.stocks if item.stock == ticker), None)
        setor = proprio.sector if proprio else None
        if not setor:
            logger.warning(f"[brapi] setor de {ticker} não encontrado na lista")
            return None

        papeis = []
        pagina, total_paginas = 1, 1
        while pagina <= min(total_paginas, MAX_PAGINAS_SETOR):
            resposta = cliente.quote.list(
                sector=setor,
                sort_by="market_cap_basic",
                sort_order="desc",
                type="stock",
                limit=str(ITENS_POR_PAGINA),
                page=str(pagina),
            )
            papeis.extend(resposta.stocks)
            total_paginas = int(resposta.total_pages or 1)
            pagina += 1

        lista, empresas = [], set()
        for item in papeis:
            if not eh_papel_inteiro(item.stock) or item.name in empresas:
                continue
            empresas.add(item.name)
            lista.append((item.stock, item.name, item.market_cap))

        if not lista:
            logger.warning(f"[brapi] lista do setor {setor} vazia para {ticker}")
            return None

        # Pelo nome também: na SHUL3, o papel que ficou na lista é o SHUL4, da mesma empresa.
        posicao = next(
            (i for i, (codigo, nome, _) in enumerate(lista, start=1) if codigo == ticker or nome == proprio.name),
            None,
        )
        return ParesDoSetor(setor=setor, posicao=posicao, total=len(lista), pares=lista[:limite])
    except Exception as e:
        logger.warning(f"[brapi] pares do setor de {ticker} indisponíveis: {type(e).__name__}")
        return None
