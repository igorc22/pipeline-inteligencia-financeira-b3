from datetime import datetime, timedelta
from newsapi import NewsApiClient
from langchain_core.tools import tool

from fluxo_financeiro.shared.config import NEWS_API_KEY
from fluxo_financeiro.shared.utils import logger
from fluxo_financeiro.tools.sanitizacao import tratar_conteudo_externo
from fluxo_financeiro.tools.web_search import buscar_na_web, origem_da_busca, registrar_falha_busca


@tool
def buscar_noticias(query: str) -> str:
    """
    Busca notícias dos últimos 30 dias sobre uma empresa ou tópico na NewsAPI.
    Use como alternativa quando buscar_noticias_web der erro ou não trouxer nada relevante.
    """
    logger.info(f"[tool] buscar_noticias: query='{query}'")
    if not NEWS_API_KEY:
        return "Erro: NEWS_API_KEY não encontrada nas variáveis de ambiente."

    try:
        newsapi = NewsApiClient(api_key=NEWS_API_KEY)
        from_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

        def _buscar(language):
            return newsapi.get_everything(
                q=query,
                language=language,
                sort_by='publishedAt',
                page_size=5,
                from_param=from_date
            ).get('articles', [])

        def _filtrar(articles, prefixo=""):
            validos = []
            for a in articles:
                titulo = a.get('title') or ''
                if titulo in ('[Removed]', ''):
                    continue
                validos.append((a, prefixo))
            return validos

        artigos = _filtrar(_buscar('pt'))

        if len(artigos) < 2:
            artigos = _filtrar(_buscar('en'), prefixo="(EN) ")

        if not artigos:
            logger.warning(f"[tool] buscar_noticias: nenhum artigo para '{query}'")
            return f"Nenhuma notícia encontrada para a busca: {query}"

        corpo = ""
        for i, (article, prefixo) in enumerate(artigos, 1):
            titulo = article.get('title', 'Sem título')
            descricao = article.get('description') or ''
            data = (article.get('publishedAt') or '')[:10]
            fonte = (article.get('source') or {}).get('name') or ''
            content = article.get('content') or ''

            fonte_str = f"[{fonte}] " if fonte else ""
            corpo += f"{i}. {prefixo}({data}) {fonte_str}{titulo}\n"
            if descricao:
                corpo += f"   {descricao}\n"
            if content:
                corpo += f"   [Contexto adicional]: {content[:200]}\n"
            corpo += "\n"

        logger.info(f"[tool] buscar_noticias: {len(artigos)} artigos encontrados")
        # Os artigos são texto de terceiros: vão dentro da tag (e pelo sanitizador, se a flag estiver ligada).
        return f"Notícias recentes sobre '{query}':\n\n" + tratar_conteudo_externo(corpo.strip(), "newsapi")

    except Exception as e:
        logger.exception(f"[tool] buscar_noticias falhou para '{query}'")
        return f"Erro ao buscar notícias: {e}"

@tool
def buscar_noticias_web(query: str) -> str:
    """
    Busca notícias em tempo real sobre uma empresa ou ação na web.
    É a busca padrão de notícias: use primeiro, para a empresa ou para o setor. Cobre
    também as últimas horas (eventos corporativos recentes, resultados, M&A).
    A resposta termina com a lista de fontes consultadas.
    """
    logger.info(f"[tool] buscar_noticias_web: query='{query}'")
    try:
        resultado = buscar_na_web(
            query,
            "Busque e resuma as notícias mais recentes sobre a consulta abaixo, no contexto da bolsa brasileira B3.\n"
            "Foque em eventos corporativos e movimentos de mercado.",
        )
        if not resultado:
            logger.warning(f"[tool] buscar_noticias_web: nenhum resultado para '{query}'")
            return f'Nenhuma notícia encontrada para: {query}'
        logger.info(f"[tool] buscar_noticias_web: ok ({len(resultado)} chars)")
        return tratar_conteudo_externo(resultado, origem_da_busca())
    except Exception as e:
        registrar_falha_busca(f"[tool] buscar_noticias_web falhou para '{query}'", e)
        return f'Erro ao buscar notícias via web search: {e}'
