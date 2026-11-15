"""Saída do servidor A2A: partes do artefato e contexto de trace."""
from unittest.mock import patch

from google.protobuf.json_format import MessageToDict
from langchain_core.messages import HumanMessage

from fluxo_financeiro.shared.types import RelatorioFinal
from servidor_a2a.saida import contexto_de_trace, montar_partes, nomes_de_trace

RELATORIO = RelatorioFinal(
    resumo="A Vale teve queda de lucro.",
    indicadores=["P/L: 77,2x"],
    contexto="Minério em queda.",
    riscos=["Preço do minério"],
    limitacoes=[],
    diagnostico="- Causa identificada: impairment",
)
MARKDOWN = "# Relatório: VALE3\n\n## Resumo\nA Vale teve queda de lucro."


def _estado(relatorio):
    return {"messages": [HumanMessage("Analise a ação VALE3"), HumanMessage(MARKDOWN, name="Consolidador")],
            "relatorio": relatorio}


def test_partes_com_relatorio():
    """Confere que a saída leva o markdown e o relatório em JSON, com o ticker ao lado."""
    texto, dados = montar_partes("VALE3", _estado(RELATORIO))
    assert texto.text == MARKDOWN
    assert texto.media_type == "text/markdown"
    assert dados.media_type == "application/json"
    assert MessageToDict(dados.data) == {"ticker": "VALE3", "relatorio": RELATORIO.model_dump()}


def test_partes_sem_relatorio():
    """Confere que, sem o relatório estruturado (Consolidador falhou), a saída leva só o texto."""
    partes = montar_partes("VALE3", _estado(None))
    assert len(partes) == 1
    assert partes[0].text == MARKDOWN


def test_trace_sem_cabecalhos():
    """Confere que, sem cabeçalho de trace, o contexto só marca a entrada."""
    assert contexto_de_trace({"content-type": "application/json"}) == {"metadata": {"entrada": "a2a"}}


def test_trace_com_pai_do_langsmith():
    """Confere que o cabeçalho langsmith-trace vira o pai da execução, com o baggage junto."""
    trace = "20261115T000000000000Z7f3b1c2a-9d4e-4f6a-8b1c-2d3e4f5a6b7c"
    contexto = contexto_de_trace({"langsmith-trace": trace, "baggage": "x=1", "host": "pipeline-b3"})
    assert contexto["parent"] == {"langsmith-trace": trace, "baggage": "x=1"}


def test_trace_ignora_pai_invalido(caplog):
    """Confere que um cabeçalho langsmith-trace inválido é descartado, em vez de derrubar a análise."""
    contexto = contexto_de_trace({"langsmith-trace": "lixo", "x-litellm-trace-id": "t1"})
    assert contexto == {"metadata": {"entrada": "a2a", "litellm_trace_id": "t1"}}
    assert "cabeçalho langsmith-trace inválido" in caplog.text


def test_trace_ignora_pai_recusado_sem_excecao():
    """Confere que um pai que o LangSmith recusa devolvendo None também sai do contexto."""
    with patch("servidor_a2a.saida.RunTree.from_headers", return_value=None):
        contexto = contexto_de_trace({"langsmith-trace": "20261115T000000000000Z7f3b1c2a-9d4e-4f6a-8b1c-2d3e4f5a6b7c"})
    assert contexto == {"metadata": {"entrada": "a2a"}}


def test_trace_com_ids_do_litellm():
    """Confere que os ids do LiteLLM entram nos metadados da execução."""
    contexto = contexto_de_trace({"x-litellm-trace-id": "t1", "x-litellm-agent-id": "a1"})
    assert contexto == {"metadata": {"entrada": "a2a", "litellm_trace_id": "t1", "litellm_agent_id": "a1"}}


def test_nomes_de_trace_sem_valores():
    """Confere que o log lista só os nomes dos cabeçalhos de trace, em ordem, nunca os valores."""
    nomes = nomes_de_trace({"authorization": "Bearer segredo", "x-litellm-trace-id": "t1",
                            "traceparent": "00-abc", "langsmith-trace": "z"})
    assert nomes == ["langsmith-trace", "traceparent", "x-litellm-trace-id"]
