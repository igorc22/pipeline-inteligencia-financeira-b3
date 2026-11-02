"""Testes de fumaça do app Streamlit com um grafo falso (sem rede, sem LLM)."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_socket
from langchain_core.messages import HumanMessage
from streamlit.testing.v1 import AppTest

from fluxo_financeiro.shared.types import RelatorioFinal


APP = str(Path(__file__).resolve().parents[2] / "dashboard" / "app.py")

RELATORIO = RelatorioFinal(
    resumo="A Petrobras apresenta fundamentos sólidos.",
    indicadores=["Preço Atual: R$ 52.71", "P/L: 5.0x", "ROE: 30.3%", "Lucro em alta"],
    contexto="Recorde de produção no pré-sal.",
    riscos=["Risco político pós-eleitoral"],
    limitacoes=[],
)
FINAL_MD = "# Relatório: PETR4\n\n## Resumo\nA Petrobras apresenta fundamentos sólidos."


@pytest.fixture(autouse=True)
def _socket_so_no_localhost():
    """O AppTest cria um event loop do asyncio, que no Windows abre um socketpair local.

    Libera o socket só para o localhost. As marcações enable_socket + allow_hosts não servem:
    juntas, deixaram passar uma conexão externa. Aqui, conectar fora continua barrado.
    """
    pytest_socket.enable_socket()
    pytest_socket.socket_allow_hosts(["127.0.0.1", "::1"])
    yield
    pytest_socket.disable_socket()


def _sup(decidido_por, proximo, tarefa=None):
    update = {"next_agent": proximo, "loop_count": 1, "decidido_por": decidido_por,
              "supervisor_reasoning": f"vai para {proximo}"}
    if tarefa:
        update["messages"] = [HumanMessage(tarefa, name="Supervisor")]
    return ("updates", {"Supervisor": update})


def _worker(nome, texto):
    return ("updates", {nome: {"messages": [HumanMessage(texto, name=nome)]}})


def _analise(relatorio=RELATORIO, final=FINAL_MD):
    """Eventos de uma análise completa da PETR4 no formato stream_mode=["updates", "values"]."""
    mensagens = [HumanMessage("Analise a ação PETR4"), HumanMessage(final, name="Consolidador")]
    return [
        _sup("llm", "YFinance", "Colete os dados da PETR4"),
        _worker("YFinance", "Dados para PETR4.SA:\nPreço Atual: R$ 52.71\nP/L:  5.0x"),
        _sup("guard", "Analyzer", "Busque notícias"),
        _worker("Analyzer", "Queda de 8% após o 2º turno."),
        _sup("guard", "Analyzer", "Busque o setor"),
        _worker("Analyzer", "Setor de óleo e gás."),
        _sup("llm", "FINISH"),
        ("updates", {"Consolidador": {"messages": [mensagens[-1]], "relatorio": relatorio}}),
        ("values", {"messages": mensagens, "loop_count": 4, "next_agent": "FINISH",
                    "relatorio": relatorio, "sinais_anomalia": []}),
    ]


@pytest.fixture
def grafo():
    falso = MagicMock()
    falso.stream.side_effect = lambda *a, **k: iter(_analise())
    with patch("fluxo_financeiro.app", falso):
        yield falso


def _rodar(ticker):
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    at.text_input(key="ticker").input(ticker)
    at.button[0].click()
    at.run()
    return at


def _textos(at):
    return " ".join(str(e.value) for e in [*at.markdown, *at.code, *at.caption])


def test_app_mostra_relatorio(grafo):
    """Test que o relatório aparece com os indicadores em quadros e as três abas."""
    at = _rodar("PETR4")

    assert not at.exception
    metricas = {m.label: m.value for m in at.metric}
    assert metricas["P/L"] == "5.0x"
    assert metricas["Preço Atual"] == "R$ 52.71"
    assert "A Petrobras apresenta fundamentos sólidos." in _textos(at)
    assert "Lucro em alta" in _textos(at)  # indicador sem ': ' vira texto
    assert len(at.tabs) == 3


def test_app_normaliza_ticker(grafo):
    """Test que espaços e minúsculas viram o ticker em maiúsculas no pedido ao grafo."""
    _rodar(" petr4 ")

    pedido = grafo.stream.call_args.args[0]["messages"][0]
    assert pedido.content == "Analise a ação PETR4"


def test_app_ticker_vazio_nao_roda(grafo):
    """Test que, sem ticker, aparece um aviso e o grafo não roda."""
    at = _rodar("   ")

    assert at.warning
    grafo.stream.assert_not_called()


def test_app_nao_roda_de_novo_sem_clique(grafo):
    """Test que um rerun sem clicar (trocar de aba, abrir expansor) não roda o grafo de novo."""
    at = _rodar("PETR4")
    at.run()

    assert grafo.stream.call_count == 1
    assert "A Petrobras apresenta fundamentos sólidos." in _textos(at)


def test_app_relatorio_nulo_mostra_fallback(grafo):
    """Test que, sem relatório estruturado, a tela avisa e mostra a mensagem final."""
    fallback = "> Não foi possível consolidar o relatório. Respostas dos agentes:"
    grafo.stream.side_effect = lambda *a, **k: iter(_analise(relatorio=None, final=fallback))

    at = _rodar("PETR4")

    assert at.warning
    assert "Não foi possível consolidar" in _textos(at)


def test_app_erro_no_grafo_mantem_passos(grafo):
    """Test que um erro no meio mostra a mensagem e mantém os passos que já chegaram."""
    def _quebra(*a, **k):
        yield from _analise()[:2]
        raise Exception("429 RESOURCE_EXHAUSTED")

    grafo.stream.side_effect = _quebra

    at = _rodar("PETR4")

    assert any("429" in e.value for e in at.error)
    assert "Preço Atual: R$ 52.71" in _textos(at)
