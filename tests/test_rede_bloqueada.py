import socket
from pathlib import Path

import pytest
from pytest_socket import SocketBlockedError


@pytest.mark.tenta_rede_de_proposito
def test_rede_bloqueada_nos_testes():
    """Test que qualquer socket é barrado: um mock esquecido falha em vez de chamar a API real."""
    with pytest.raises(SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def test_rede_engolida_por_except_reprova_o_teste(pytester, monkeypatch):
    """Test que um socket barrado dentro de try/except (como nas tools) ainda reprova o teste."""
    conftest = Path(__file__).with_name("conftest.py").read_text(encoding="utf-8")
    pytester.makeconftest(conftest)
    pytester.makepyfile(
        """
        import socket

        def test_mock_esquecido():
            try:
                socket.socket()
            except Exception:
                pass  # as tools devolvem "Erro ao ..." em vez de levantar
        """
    )

    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")  # no Windows a saída sairia em cp1252
    resultado = pytester.runpytest_subprocess("--disable-socket", "-p", "no:cacheprovider")

    resultado.assert_outcomes(passed=1, errors=1)
    resultado.stdout.fnmatch_lines(["*tentou usar a rede*"])
