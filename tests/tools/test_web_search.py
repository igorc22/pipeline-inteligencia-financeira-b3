from unittest.mock import MagicMock, patch

from fluxo_financeiro.tools.news import buscar_noticias_web
from fluxo_financeiro.tools.web_search import MAX_FONTES, pesquisar_na_web


def _chunk(titulo, url):
    chunk = MagicMock()
    chunk.web.title = titulo
    chunk.web.uri = url
    return chunk


def _resposta_gemini(texto, chunks=None):
    response = MagicMock()
    response.text = texto
    candidato = MagicMock()
    candidato.grounding_metadata.grounding_chunks = chunks
    response.candidates = [candidato]
    return response


# ---------------------------------------------------------------------------
# pesquisar_na_web (helper com o SDK do Google mockado)
# ---------------------------------------------------------------------------

@patch('fluxo_financeiro.tools.web_search.genai.Client')
def test_pesquisar_na_web_usa_google_search(mock_client_cls):
    """Test que a chamada ao Gemini liga a tool de Google Search."""
    mock_client_cls.return_value.models.generate_content.return_value = _resposta_gemini("resumo")

    pesquisar_na_web("notícias da VALE3")

    kwargs = mock_client_cls.return_value.models.generate_content.call_args.kwargs
    assert kwargs["contents"] == "notícias da VALE3"
    assert kwargs["config"].tools[0].google_search is not None


@patch('fluxo_financeiro.tools.web_search.genai.Client')
def test_pesquisar_na_web_lista_fontes_sem_repetir(mock_client_cls):
    """Test que as fontes do grounding aparecem no fim, sem URLs duplicadas."""
    chunks = [_chunk("valor.com.br", "https://a"), _chunk("valor.com.br", "https://a"), _chunk("infomoney.com.br", "https://b")]
    mock_client_cls.return_value.models.generate_content.return_value = _resposta_gemini("Vale caiu 5%.", chunks)

    resultado = pesquisar_na_web("x")

    assert resultado.startswith("Vale caiu 5%.")
    assert "Fontes:" in resultado
    assert resultado.count("https://a") == 1
    assert "infomoney.com.br: https://b" in resultado


@patch('fluxo_financeiro.tools.web_search.genai.Client')
def test_pesquisar_na_web_limita_fontes(mock_client_cls):
    """Test que no máximo MAX_FONTES fontes são listadas."""
    chunks = [_chunk(f"site{i}", f"https://{i}") for i in range(MAX_FONTES + 3)]
    mock_client_cls.return_value.models.generate_content.return_value = _resposta_gemini("texto", chunks)

    resultado = pesquisar_na_web("x")

    assert resultado.count("https://") == MAX_FONTES


@patch('fluxo_financeiro.tools.web_search.genai.Client')
def test_pesquisar_na_web_sem_texto_retorna_vazio(mock_client_cls):
    """Test que resposta sem texto vira string vazia (a tool decide a mensagem)."""
    mock_client_cls.return_value.models.generate_content.return_value = _resposta_gemini(None)

    assert pesquisar_na_web("x") == ""


# ---------------------------------------------------------------------------
# buscar_noticias_web (tool do Analyzer)
# ---------------------------------------------------------------------------

@patch('fluxo_financeiro.tools.news.pesquisar_na_web')
def test_buscar_noticias_web_retorna_resultado(mock_pesquisa):
    """Test que a tool repassa o resumo com fontes."""
    mock_pesquisa.return_value = "Resumo.\n\nFontes:\n- site: https://x"

    resultado = buscar_noticias_web.invoke("WEGE3")

    assert "Resumo." in resultado
    assert "WEGE3" in mock_pesquisa.call_args.args[0]


@patch('fluxo_financeiro.tools.news.pesquisar_na_web')
def test_buscar_noticias_web_sem_resultado(mock_pesquisa):
    """Test mensagem amigável quando a busca não traz nada."""
    mock_pesquisa.return_value = ""

    assert "Nenhuma notícia encontrada" in buscar_noticias_web.invoke("XPTO3")


@patch('fluxo_financeiro.tools.news.pesquisar_na_web')
def test_buscar_noticias_web_erro_vira_string(mock_pesquisa):
    """Test que exceção (ex: chave inválida) vira string de erro, não derruba o agente."""
    mock_pesquisa.side_effect = Exception("API key not valid")

    resultado = buscar_noticias_web.invoke("WEGE3")

    assert resultado.startswith("Erro ao buscar notícias via web search")
