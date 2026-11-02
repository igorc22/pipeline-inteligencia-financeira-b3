from unittest.mock import patch

import pytest
from langchain_core.messages import HumanMessage

from fluxo_financeiro.agents.consolidator import (
    CONSOLIDADOR_PROMPT,
    LIMITACAO_SEM_DADOS,
    LIMITACAO_SEM_NOTICIAS,
    consolidar,
    formatar_relatorio,
    relatorio_de_emergencia,
)
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


# ---------------------------------------------------------------------------
# consolidar (LLM mockado; o pós-processamento em código é o que se testa)
# ---------------------------------------------------------------------------

HIST = [
    HumanMessage("Analise VALE3"),
    HumanMessage("P/L 74,7x", name="YFinance"),
    HumanMessage("Busque notícias", name="Supervisor"),
    HumanMessage("Minério caiu", name="Analyzer"),
    HumanMessage("Busque o setor", name="Supervisor"),
    HumanMessage("Setor fraco", name="Analyzer"),
]
DIAG = "- Causa identificada: impairment de níquel\n- Natureza do evento: pontual"


@pytest.fixture
def mock_llm():
    """LLM do Consolidador mockado: devolve uma cópia de REL (que vem com diagnóstico preenchido)."""
    with patch("fluxo_financeiro.agents.consolidator.llm") as llm:
        llm.with_structured_output.return_value.invoke.side_effect = lambda _msgs: REL.model_copy()
        yield llm


def _enviado(mock_llm):
    """(system prompt, insumos) que foram mandados ao LLM."""
    enviadas = mock_llm.with_structured_output.return_value.invoke.call_args.args[0]
    return enviadas[0].content, enviadas[-1].content


def test_consolidar_envia_so_respostas_dos_agentes(mock_llm):
    """Test que o LLM recebe o prompt e as respostas dos workers, sem as tarefas do Supervisor."""
    consolidar(HIST)

    mock_llm.with_structured_output.assert_called_once_with(RelatorioFinal)
    system, insumos = _enviado(mock_llm)
    assert system == CONSOLIDADOR_PROMPT
    assert "P/L 74,7x" in insumos and "Setor fraco" in insumos
    assert "Busque notícias" not in insumos and "Busque o setor" not in insumos


def test_consolidar_copia_diagnostico_do_investigator_literalmente(mock_llm):
    """Test que o diagnóstico é o texto do Investigator, mesmo se o LLM escrever outro."""
    mock_llm.with_structured_output.return_value.invoke.side_effect = (
        lambda _msgs: REL.model_copy(update={"diagnostico": "resumo inventado"})
    )

    relatorio = consolidar(HIST + [HumanMessage(DIAG, name="Investigator")])

    assert relatorio.diagnostico == DIAG


def test_consolidar_sem_investigator_zera_diagnostico(mock_llm):
    """Test que, sem Investigator no histórico, o diagnóstico fica nulo."""
    assert consolidar(HIST).diagnostico is None


def test_consolidar_aponta_etapas_que_faltaram(mock_llm):
    """Test que etapas ausentes (hard stop, falha) viram limitações escritas em código."""
    sem_nada = consolidar([HumanMessage("Analise VALE3")])
    assert LIMITACAO_SEM_DADOS in sem_nada.limitacoes
    assert LIMITACAO_SEM_NOTICIAS in sem_nada.limitacoes

    completo = consolidar(HIST)
    assert LIMITACAO_SEM_DADOS not in completo.limitacoes
    assert LIMITACAO_SEM_NOTICIAS not in completo.limitacoes


def test_consolidar_zera_secoes_de_etapas_que_nao_rodaram(mock_llm):
    """Test que, sem YFinance/Analyzer, indicadores e contexto do LLM são descartados (não finge ter dados)."""
    sem_nada = consolidar([HumanMessage("Analise VALE3")])  # REL vem com indicadores e contexto preenchidos
    assert sem_nada.indicadores == []
    assert sem_nada.contexto == ""

    completo = consolidar(HIST)
    assert completo.indicadores == REL.indicadores
    assert completo.contexto == REL.contexto


def test_consolidar_erro_do_llm_sobe(mock_llm):
    """Test que erro do LLM sobe: quem decide o fallback é o nó do grafo."""
    mock_llm.with_structured_output.return_value.invoke.side_effect = Exception("429")

    with pytest.raises(Exception, match="429"):
        consolidar(HIST)
