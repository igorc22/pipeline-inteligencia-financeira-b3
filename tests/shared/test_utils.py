import pytest

from fluxo_financeiro.shared.utils import extrair_ticker


@pytest.mark.parametrize("texto, esperado", [
    ("Analise a ação VALE3", "VALE3"),
    ("analise a vale3 por favor", "VALE3"),      # minúsculas
    ("Como está PETR4.SA hoje?", "PETR4"),       # com sufixo .SA
    ("E o TAEE11?", "TAEE11"),                   # units com 2 dígitos
    ("Compare WEGE3 com VALE3", "WEGE3"),        # pega o primeiro
    ("Analise a Vale", None),                    # nome da empresa não é ticker
    ("ABCDE12 não é ticker", None),              # 5 letras
])
def test_extrair_ticker(texto, esperado):
    """Test que extrai o ticker da B3 (4 letras + 1-2 dígitos) do pedido do usuário."""
    assert extrair_ticker(texto) == esperado
