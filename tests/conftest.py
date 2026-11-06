"""Configuração global dos testes.

Desliga o tracing do LangSmith antes de qualquer import do projeto: com LANGSMITH_TRACING=true
no .env, cada tool.invoke() dos testes viraria um trace no projeto real, poluindo os dados e
fazendo os testes dependerem de rede. O load_dotenv() de config.py não sobrescreve variáveis
que já existem no ambiente, então o valor abaixo prevalece.
"""
import os

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
# Com SANITIZACAO_ATIVA=true no .env, cada tool de busca chamaria o classificador (Gemini) nos testes.
# Os testes que precisam da flag ligada fazem patch no módulo e mockam o LLM.
os.environ["SANITIZACAO_ATIVA"] = "false"

pytest_plugins = ["pytester"]


import pytest  # noqa: E402  (depois das variáveis de ambiente, de propósito)


@pytest.fixture(autouse=True)
def _reprova_teste_que_tentou_rede(request, recwarn):
    """Reprova o teste que tentou abrir socket, mesmo que o erro tenha sido engolido.

    O pytest-socket levanta SocketBlockedError, mas as tools capturam qualquer Exception e
    devolvem "Erro ao ...": um mock esquecido viraria um teste verde. O aviso que o
    pytest-socket emite junto com o erro não é engolido, e é ele que se confere aqui.
    """
    yield
    if request.node.get_closest_marker("tenta_rede_de_proposito"):
        return
    avisos = [w for w in recwarn if "tried to use socket" in str(w.message)]
    if avisos:
        pytest.fail(f"O teste tentou usar a rede (mock esquecido?): {avisos[0].message}")
