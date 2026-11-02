import socket

import pytest
from pytest_socket import SocketBlockedError


def test_rede_bloqueada_nos_testes():
    """Test que qualquer socket é barrado: um mock esquecido falha em vez de chamar a API real."""
    with pytest.raises(SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
