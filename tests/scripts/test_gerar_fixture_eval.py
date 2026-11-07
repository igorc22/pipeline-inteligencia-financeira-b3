"""Checagens do scripts/gerar_fixture_eval.py sem chamada real: grafo de verdade com agentes e LLMs falsos."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, messages_from_dict
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from fluxo_financeiro.shared.types import RelatorioFinal, RouteDecision, SinalAnomalia

_CAMINHO = Path(__file__).resolve().parents[2] / "scripts" / "gerar_fixture_eval.py"
_spec = importlib.util.spec_from_file_location("gerar_fixture_eval", _CAMINHO)
gerar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gerar)

REL = RelatorioFinal(resumo="Resumo da análise.", indicadores=["P/L: 74,7x"], contexto="notícias",
                     riscos=["minério"], limitacoes=[])
SINAL = SinalAnomalia(tipo="queda_lucro", descricao="lucro caiu 45%")


# ---------------------------------------------------------------------------
# Agentes falsos: create_agent de verdade com um modelo que pede uma tool e conclui
# ---------------------------------------------------------------------------

class ModeloQuePedeUmaTool(BaseChatModel):
    """Modelo falso que pede a sua tool uma vez e conclui ao ver a ToolMessage."""

    nome_tool: str
    chamadas: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-uma-tool"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.chamadas += 1
        if isinstance(messages[-1], ToolMessage) or self.chamadas > 10:  # trava contra laço infinito
            resposta = AIMessage(content=f"conclusão depois de {self.nome_tool}")
        else:
            resposta = AIMessage(content="", tool_calls=[{
                "name": self.nome_tool,
                "args": {"consulta": "VALE3"},
                "id": f"{self.nome_tool}-{self.chamadas}",
            }])
        return ChatResult(generations=[ChatGeneration(message=resposta)])


@tool
def dados_falsos(consulta: str) -> str:
    """Dados de mercado falsos."""
    return f"preço e P/L de {consulta}"


@tool
def noticias_falsas(consulta: str) -> str:
    """Notícias falsas."""
    return f"notícias de {consulta}"


@tool
def fatos_falsos(consulta: str) -> str:
    """Fatos relevantes falsos."""
    return f"impairment de {consulta}"


def _agente_falso(ferramenta):
    return create_agent(model=ModeloQuePedeUmaTool(nome_tool=ferramenta.name), tools=[ferramenta])


@pytest.fixture
def grafo_com_agentes_falsos():
    """Troca os 3 agentes por create_agent com modelo falso, o detector (devolve [SINAL]) e os LLMs
    do Supervisor (só decide a etapa 1) e do Consolidador (devolve REL), no molde do grafo_mockado."""
    with patch("fluxo_financeiro.graph.graph.yfinance_agent", _agente_falso(dados_falsos)), \
         patch("fluxo_financeiro.graph.graph.analyzer_agent", _agente_falso(noticias_falsas)), \
         patch("fluxo_financeiro.graph.graph.investigator_agent", _agente_falso(fatos_falsos)), \
         patch("fluxo_financeiro.graph.graph.detectar_sinais_anomalia", return_value=[SINAL]), \
         patch("fluxo_financeiro.graph.supervisor.llm") as llm, \
         patch("fluxo_financeiro.agents.consolidator.llm") as llm_consolidador:
        llm.with_structured_output.return_value.invoke.side_effect = [
            RouteDecision(reasoning="sem dados", next_agent="YFinance", task_for_agent="Colete os dados da VALE3"),
        ]
        llm_consolidador.with_structured_output.return_value.invoke.return_value = REL
        yield


# ---------------------------------------------------------------------------
# coletar
# ---------------------------------------------------------------------------

def test_coletar_separa_passagens_por_namespace():
    """Confere que duas passagens do Analyzer viram duas entradas, cada uma com as suas tools."""
    eventos = [
        (("Analyzer:a",), "updates", {"tools": {"messages": [ToolMessage("n1", name="buscar_noticias_web", tool_call_id="1")]}}),
        (("Analyzer:b",), "updates", {"tools": {"messages": [ToolMessage("s1", name="buscar_noticias_web", tool_call_id="2")]}}),
        ((), "values", {"messages": [], "relatorio": None}),
    ]
    estado, passagens = gerar.coletar(eventos)
    assert [(p["agente"], p["n"], [t["conteudo"] for t in p["tools"]]) for p in passagens] == [
        ("Analyzer", 1, ["n1"]), ("Analyzer", 2, ["s1"])]
    assert estado == {"messages": [], "relatorio": None}


def test_coletar_ignora_update_vazio_e_guarda_passagem_sem_tools():
    """Confere que update None não quebra e que um agente que não chamou tool ainda tem a sua passagem."""
    eventos = [
        (("YFinance:a",), "updates", None),
        (("YFinance:a",), "updates", "nao_e_dict"),
        (("YFinance:a",), "updates", {"model": None}),
        (("YFinance:a",), "updates", {"model": {"messages": [AIMessage("respondi sem tool")]}}),
        ((), "updates", {"YFinance": {"messages": [HumanMessage("d", name="YFinance")]}}),
        ((), "values", {"messages": ["fim"]}),
    ]
    estado, passagens = gerar.coletar(eventos)
    assert passagens == [{"agente": "YFinance", "n": 1, "tools": []}]
    assert estado == {"messages": ["fim"]}


def test_coletar_com_grafo_real_e_agentes_falsos(grafo_com_agentes_falsos):
    """Confere, no app de verdade com os 3 agentes trocados por create_agent com modelo falso,
    que as saídas das tools de cada passagem chegam ao script."""
    estado, passagens = gerar.rodar("VALE3")
    assert [(p["agente"], p["n"]) for p in passagens] == [
        ("YFinance", 1), ("Analyzer", 1), ("Analyzer", 2), ("Investigator", 1)]
    assert all(len(p["tools"]) == 1 for p in passagens)
    assert all(p["tools"][0]["conteudo"] for p in passagens)
    assert estado["messages"][-1].name == "Consolidador"
    assert estado["relatorio"] is not None


# ---------------------------------------------------------------------------
# montar_fixture
# ---------------------------------------------------------------------------

def test_montar_fixture_recusa_relatorio_ausente():
    """Confere que análise cujo Consolidador caiu no fallback não vira fixture."""
    with pytest.raises(ValueError, match="relatório ausente"):
        gerar.montar_fixture("VALE3", {"messages": [], "relatorio": None, "sinais_anomalia": []}, [], "m", "t")


def test_montar_fixture_ida_e_volta_das_mensagens():
    """Confere que messages_from_dict(fixture["messages"]) devolve os mesmos nomes e textos do state."""
    msgs = [HumanMessage("Analise a ação VALE3"), HumanMessage("lucro ≈ US$ 1 bi", name="YFinance"),
            HumanMessage("# Relatório", name="Consolidador")]
    fx = gerar.montar_fixture("VALE3", {"messages": msgs, "relatorio": REL, "sinais_anomalia": [SINAL]}, [], "m", "t")
    volta = messages_from_dict(fx["messages"])
    assert [(m.name, m.content) for m in volta] == [(m.name, m.content) for m in msgs]
    assert fx["relatorio"] == REL.model_dump()
    assert fx["sinais_anomalia"] == [SINAL.model_dump()]
    assert fx["versao"] == gerar.VERSAO_FIXTURE
    assert json.loads(json.dumps(fx, ensure_ascii=False)) == fx


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def test_main_grava_utf8_e_cria_a_pasta(tmp_path):
    """Confere que main cria a pasta das fixtures e grava em UTF-8 texto fora do cp1252, sem depender da localidade."""
    pasta = tmp_path / "fixtures" / "nova"
    eventos = [
        (("Analyzer:a",), "updates", {"tools": {"messages": [
            ToolMessage("minério ≈ US$ 100 → queda − 3% 中 🙂", name="buscar_noticias_web", tool_call_id="1")]}}),
        ((), "values", {"messages": [HumanMessage("Analise a ação VALE3"), HumanMessage("# Relatório", name="Consolidador")],
                        "relatorio": REL, "sinais_anomalia": []}),
    ]
    with patch.object(gerar, "app") as app_falso:
        app_falso.stream.return_value = iter(eventos)
        assert gerar.main(["VALE3"], pasta=pasta) == 0
    fx = json.loads((pasta / "vale3.json").read_text(encoding="utf-8"))
    assert fx["passagens"][0]["tools"][0]["conteudo"] == "minério ≈ US$ 100 → queda − 3% 中 🙂"


def test_main_nao_grava_quando_relatorio_ausente(tmp_path):
    """Confere que, com o Consolidador no fallback, main sai com 1 e não deixa arquivo."""
    with patch.object(gerar, "app") as app_falso:
        app_falso.stream.return_value = iter([((), "values", {"messages": [], "relatorio": None, "sinais_anomalia": []})])
        assert gerar.main(["VALE3"], pasta=tmp_path) == 1
    assert not list(tmp_path.glob("*.json"))


def test_main_recusa_ticker_invalido_sem_rodar_o_grafo(tmp_path):
    """Confere que ticker fora do formato da B3 é recusado antes do grafo."""
    with patch.object(gerar, "app") as app_falso:
        assert gerar.main(["isso nao e ticker"], pasta=tmp_path) == 2
        app_falso.stream.assert_not_called()
