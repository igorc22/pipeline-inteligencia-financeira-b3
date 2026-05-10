import pytest
from unittest.mock import patch, MagicMock
from fluxo_financeiro.tools.news import buscar_noticias


def test_buscar_noticias_retorna_string():
    """Test that buscar_noticias returns a string."""
    with patch('fluxo_financeiro.tools.news.NewsApiClient') as mock_api:
        mock_instance = MagicMock()
        mock_api.return_value = mock_instance
        mock_instance.get_everything.return_value = {
            'articles': [
                {
                    'title': 'Test Article',
                    'description': 'Test Description',
                    'publishedAt': '2024-01-01T00:00:00Z'
                }
            ]
        }

        result = buscar_noticias.invoke("test query")
        assert isinstance(result, str)
        assert len(result) > 0


def test_buscar_noticias_no_articles():
    """Test that buscar_noticias handles empty results gracefully."""
    with patch('fluxo_financeiro.tools.news.NewsApiClient') as mock_api:
        mock_instance = MagicMock()
        mock_api.return_value = mock_instance
        mock_instance.get_everything.return_value = {'articles': []}

        result = buscar_noticias.invoke("nonexistent company")
        assert "Nenhuma notícia encontrada" in result


def test_inclui_source_e_content():
    """Test que source.name e content aparecem no output."""
    with patch('fluxo_financeiro.tools.news.NewsApiClient') as mock_api:
        mock_instance = MagicMock()
        mock_api.return_value = mock_instance
        mock_instance.get_everything.return_value = {
            'articles': [
                {
                    'title': 'WEG lucro recorde',
                    'description': 'Empresa registrou crescimento de 18%',
                    'publishedAt': '2025-05-08T10:00:00Z',
                    'source': {'name': 'Valor Econômico'},
                    'content': 'Texto adicional sobre a empresa e seus resultados'
                },
                {
                    'title': 'WEG expansao internacional',
                    'description': 'Nova fabrica na Europa',
                    'publishedAt': '2025-05-07T10:00:00Z',
                    'source': {'name': 'InfoMoney'},
                    'content': 'Contexto adicional sobre expansao'
                }
            ]
        }
        result = buscar_noticias.invoke("WEG")
        assert "Valor Econômico" in result
        assert "Texto adicional sobre a empresa" in result


def test_filtra_artigos_removed():
    """Test que artigos [Removed] não aparecem no output."""
    with patch('fluxo_financeiro.tools.news.NewsApiClient') as mock_api:
        mock_instance = MagicMock()
        mock_api.return_value = mock_instance
        mock_instance.get_everything.return_value = {
            'articles': [
                {
                    'title': '[Removed]',
                    'description': '[Removed]',
                    'publishedAt': '2025-05-08T10:00:00Z',
                    'source': {'name': 'Unknown'},
                    'content': None
                }
            ]
        }
        result = buscar_noticias.invoke("WEGE3")
        assert "Nenhuma notícia encontrada" in result


def test_fallback_ingles():
    """Test que busca EN é acionada quando PT retorna menos de 2 artigos válidos."""
    with patch('fluxo_financeiro.tools.news.NewsApiClient') as mock_api:
        mock_instance = MagicMock()
        mock_api.return_value = mock_instance
        mock_instance.get_everything.side_effect = [
            {'articles': []},
            {
                'articles': [
                    {
                        'title': 'WEG reports record profit',
                        'description': 'Company posted strong growth',
                        'publishedAt': '2025-05-08T10:00:00Z',
                        'source': {'name': 'Reuters'},
                        'content': 'Additional context about the company'
                    },
                    {
                        'title': 'WEG expands internationally',
                        'description': 'New factory opening in Europe',
                        'publishedAt': '2025-05-07T10:00:00Z',
                        'source': {'name': 'Bloomberg'},
                        'content': 'More details on expansion'
                    }
                ]
            }
        ]
        result = buscar_noticias.invoke("WEGE3")
        assert "(EN)" in result
        assert "WEG reports record profit" in result
