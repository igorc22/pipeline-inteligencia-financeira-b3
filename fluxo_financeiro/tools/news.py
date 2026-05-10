from datetime import datetime, timedelta
import anthropic
from newsapi import NewsApiClient
from langchain_core.tools import tool

from fluxo_financeiro.shared.config import NEWS_API_KEY, MODEL
from fluxo_financeiro.shared.utils import logger


@tool
def buscar_noticias(query: str) -> str:
    """
    Busca as notícias mais recentes sobre uma empresa ou tópico.
    Use esta ferramenta para entender o contexto atual ou motivos de oscilação de mercado.
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

        resultado = f"Notícias recentes sobre '{query}':\n\n"
        for i, (article, prefixo) in enumerate(artigos, 1):
            titulo = article.get('title', 'Sem título')
            descricao = article.get('description') or ''
            data = (article.get('publishedAt') or '')[:10]
            fonte = (article.get('source') or {}).get('name') or ''
            content = article.get('content') or ''

            fonte_str = f"[{fonte}] " if fonte else ""
            resultado += f"{i}. {prefixo}({data}) {fonte_str}{titulo}\n"
            if descricao:
                resultado += f"   {descricao}\n"
            if content:
                resultado += f"   [Contexto adicional]: {content[:200]}\n"
            resultado += "\n"

        logger.info(f"[tool] buscar_noticias: {len(artigos)} artigos encontrados")
        return resultado

    except Exception as e:
        logger.exception(f"[tool] buscar_noticias falhou para '{query}'")
        return f"Erro ao buscar notícias: {e}"

@tool
def buscar_noticias_web(query: str) -> str:
    """
    Busca noticias em tempo real sobre uma empresa ou acao via Anthropic Web Search.
    Use esta ferramenta quando buscar_noticias retornar poucos resultados ou quando
    precisar de noticias das ultimas horas (eventos corporativos recentes, resultados, M&A).
    """
    logger.info(f"[tool] buscar_noticias_web: query='{query}'")
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[{
                'role': 'user',
                'content': (
                    f'Busque e resuma as noticias mais recentes sobre {query} '
                    f'na bolsa brasileira B3. Foque em eventos corporativos e '
                    f'movimentos de mercado. Seja conciso (max 3 paragrafos).'
                )
            }],
            tools=[{'type': 'web_search_20250305', 'name': 'web_search'}]
        )
        textos = [block.text for block in response.content if block.type == 'text']
        if not textos:
            logger.warning(f"[tool] buscar_noticias_web: nenhum resultado para '{query}'")
            return f'Nenhuma noticia encontrada para: {query}'
        logger.info(f"[tool] buscar_noticias_web: ok ({len(textos)} blocos de texto)")
        return '\n'.join(textos)
    except Exception as e:
        logger.exception(f"[tool] buscar_noticias_web falhou para '{query}'")
        return f'Erro ao buscar noticias via web search: {e}'