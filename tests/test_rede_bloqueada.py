import socket
import tomllib
from pathlib import Path

import pytest
from pytest_socket import SocketBlockedError

RAIZ = Path(__file__).resolve().parents[1]


@pytest.mark.tenta_rede_de_proposito
def test_rede_bloqueada_nos_testes():
    """Confere que qualquer socket é barrado: um mock esquecido falha em vez de chamar a API real."""
    with pytest.raises(SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def test_rede_engolida_por_except_reprova_o_teste(pytester, monkeypatch):
    """Confere que um socket barrado dentro de try/except (como nas tools) ainda reprova o teste."""
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
    resultado = pytester.runpytest_subprocess("--disable-socket", "-p", "no:cacheprovider", "-p", "no:deepeval")

    resultado.assert_outcomes(passed=1, errors=1)
    resultado.stdout.fnmatch_lines(["*tentou usar a rede*"])


def test_teste_comum_depois_de_eval_continua_sem_rede(pytester, monkeypatch):
    """Confere que o enable_socket de um eval não vaza para o teste seguinte."""
    pytester.makepyfile(
        """
        import socket
        import pytest
        from pytest_socket import SocketBlockedError

        @pytest.mark.enable_socket
        def test_a_eval():
            socket.socket().close()

        def test_b_comum():
            with pytest.raises(SocketBlockedError):
                socket.socket()
        """
    )
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    resultado = pytester.runpytest_subprocess("--disable-socket", "-p", "no:cacheprovider", "-p", "no:deepeval")
    resultado.assert_outcomes(passed=2)


def test_pytest_padrao_exclui_evals_e_bloqueia_rede():
    """Confere o contrato do pyproject: rede bloqueada, evals fora e plugin da deepeval desligado."""
    config = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]
    assert "--disable-socket" in config["addopts"]
    assert "-m 'not eval'" in config["addopts"]
    assert "-p no:deepeval" in config["addopts"]
    assert any(m.startswith("eval:") for m in config["markers"])
