from langchain_core.messages import HumanMessage

from fluxo_financeiro.agents.consolidator import formatar_relatorio, relatorio_de_emergencia
from fluxo_financeiro.shared.types import RelatorioFinal

REL = RelatorioFinal(
    resumo="Lucro caiu.",
    indicadores=["P/L: 74,7x"],
    contexto="Minério em queda.",
    riscos=["Preço do minério"],
    limitacoes=["Sem notícias do setor"],
    diagnostico="- Causa identificada: impairment",
)


# ---------------------------------------------------------------------------
# formatar_relatorio (markdown montado em código)
# ---------------------------------------------------------------------------

def test_formatar_relatorio_tem_secoes_na_ordem():
    """Test que o relatório tem título com o ticker e as seções na ordem fixa."""
    md = formatar_relatorio(REL, "VALE3")

    assert md.startswith("# Relatório: VALE3")
    titulos = ["## Resumo", "## Indicadores", "## Notícias e setor",
               "## Diagnóstico da anomalia", "## Riscos", "## Limitações"]
    posicoes = [md.index(t) for t in titulos]
    assert posicoes == sorted(posicoes)
    assert "- P/L: 74,7x" in md


def test_formatar_relatorio_sem_diagnostico_omite_secao():
    """Test que, sem Investigator, a seção de diagnóstico não aparece."""
    md = formatar_relatorio(REL.model_copy(update={"diagnostico": None}), "WEGE3")

    assert "Diagnóstico" not in md


def test_formatar_relatorio_omite_secoes_vazias():
    """Test que lista vazia não vira título solto no relatório."""
    md = formatar_relatorio(REL.model_copy(update={"indicadores": [], "riscos": [], "limitacoes": []}), "WEGE3")

    assert "## Indicadores" not in md
    assert "## Riscos" not in md
    assert "## Limitações" not in md


def test_formatar_relatorio_sem_ticker():
    """Test que, sem ticker identificado, o título é genérico."""
    assert formatar_relatorio(REL, None).startswith("# Relatório da análise")


# ---------------------------------------------------------------------------
# relatorio_de_emergencia (fallback quando o LLM do Consolidador falha)
# ---------------------------------------------------------------------------

def test_relatorio_de_emergencia_junta_so_os_agentes():
    """Test que o fallback junta só as respostas dos workers, sem tarefas nem o pedido."""
    msgs = [
        HumanMessage("Analise VALE3"),
        HumanMessage("dados X", name="YFinance"),
        HumanMessage("Busque notícias", name="Supervisor"),
        HumanMessage("notícias Y", name="Analyzer"),
    ]

    texto = relatorio_de_emergencia(msgs)

    assert texto.startswith("> Não foi possível consolidar")
    assert "dados X" in texto and "notícias Y" in texto
    assert "Busque notícias" not in texto
    assert "Analise VALE3" not in texto
