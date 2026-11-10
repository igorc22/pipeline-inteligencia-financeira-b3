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

from fluxo_financeiro.agents.pesquisa import criar_grafo_pesquisa
from fluxo_financeiro.shared.types import (
    CriticaPesquisa,
    DiagnosticoPesquisa,
    PerguntasPesquisa,
    PesquisaFeita,
    RelatorioFinal,
    RouteDecision,
    SinalAnomalia,
)
from tests.agents.llm_falso import LlmFalso

_CAMINHO = Path(__file__).resolve().parents[2] / "scripts" / "gerar_fixture_eval.py"
_spec = importlib.util.spec_from_file_location("gerar_fixture_eval", _CAMINHO)
gerar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gerar)

REL = RelatorioFinal(resumo="Resumo da análise.", indicadores=["P/L: 74,7x"], contexto="notícias",
                     riscos=["minério"], limitacoes=[])
SINAL = SinalAnomalia(tipo="queda_lucro", descricao="lucro caiu 45%")


@pytest.fixture(autouse=True)
def _ticker_existe():
    """A Brapi confere o ticker na entrada: aqui ela é sempre falsa (a rede é bloqueada nos testes)."""
    with patch("fluxo_financeiro.tools.brapi.ticker_existe", return_value=True) as existe, \
         patch("fluxo_financeiro.tools.brapi.sugerir_ticker", return_value=None) as sugere:
        yield existe, sugere


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


def _agente_falso(ferramenta):
    return create_agent(model=ModeloQuePedeUmaTool(nome_tool=ferramenta.name), tools=[ferramenta])


def _subgrafo_falso():
    """Subgrafo de pesquisa de verdade com o LLM falso: 2 perguntas, síntese e crítico que aprova."""
    return criar_grafo_pesquisa(LlmFalso({
        PerguntasPesquisa: [PerguntasPesquisa(perguntas=["Por que o lucro caiu?", "Houve impairment?"])],
        DiagnosticoPesquisa: [DiagnosticoPesquisa(causa="impairment", natureza="pontual",
                                                  evidencias=["baixa de US$ 1 bi"], impacto="pontual")],
        CriticaPesquisa: [CriticaPesquisa(aprovado=True, lacunas=[])],
    }))


@pytest.fixture
def grafo_com_agentes_falsos():
    """Troca o YFinance e o Analyzer por create_agent com modelo falso, o subgrafo do Investigator pelo
    de verdade com LLM falso (busca e histórico trimestral mockados), o detector (devolve [SINAL]), o
    bloco do Banco Central (fixo, sem rede) e os LLMs do Supervisor (só decide a etapa 1) e do
    Consolidador (devolve REL), no molde do grafo_mockado."""
    with patch("fluxo_financeiro.graph.graph.yfinance_agent", _agente_falso(dados_falsos)), \
         patch("fluxo_financeiro.graph.graph.analyzer_agent", _agente_falso(noticias_falsas)), \
         patch("fluxo_financeiro.agents.pesquisa.grafo_pesquisa", _subgrafo_falso()), \
         patch("fluxo_financeiro.agents.pesquisa.pesquisar_pergunta",
               side_effect=lambda p, t: f"achado: {p}\nFontes: vale.com"), \
         patch("fluxo_financeiro.agents.pesquisa.buscar_historico_trimestral") as historico, \
         patch("fluxo_financeiro.graph.graph.detectar_sinais_anomalia", return_value=[SINAL]), \
         patch("fluxo_financeiro.graph.graph.indicadores_economicos_em_texto",
               return_value="INDICADORES ECONÔMICOS (Banco Central, buscados em código):\n- CDI: 13.65% a.a."), \
         patch("fluxo_financeiro.graph.supervisor.llm") as llm, \
         patch("fluxo_financeiro.agents.consolidator.llm") as llm_consolidador:
        llm.with_structured_output.return_value.invoke.side_effect = [
            RouteDecision(reasoning="sem dados", next_agent="YFinance", task_for_agent="Colete os dados da VALE3"),
        ]
        historico.invoke.return_value = "Net Income 4T25: -3.8B"
        llm_consolidador.with_structured_output.return_value.invoke.return_value = REL
        yield


# ---------------------------------------------------------------------------
# coletar
# ---------------------------------------------------------------------------

def test_coletar_separa_passagens_por_namespace():
    """Confere que duas passagens do mesmo agente (o reenvio do retry) viram duas entradas, cada uma com as suas tools."""
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
    """Confere que, no app de verdade com YFinance e Analyzer em create_agent com modelo falso e o
    subgrafo de pesquisa no Investigator, as saídas das tools chegam ao script, o Investigator ainda
    tem a sua passagem (sem tools: o subgrafo não usa ToolMessage) e a pesquisa chega ao state."""
    estado, passagens = gerar.rodar("VALE3")
    assert [(p["agente"], p["n"]) for p in passagens] == [
        ("YFinance", 1), ("Analyzer", 1), ("Investigator", 1)]
    tools_por_agente = {p["agente"]: [t["nome"] for t in p["tools"]] for p in passagens}
    assert tools_por_agente == {"YFinance": ["dados_falsos"], "Analyzer": ["noticias_falsas"], "Investigator": []}
    assert all(t["conteudo"] for p in passagens for t in p["tools"])
    assert estado["messages"][-1].name == "Consolidador"
    assert estado["relatorio"] is not None
    pesquisa = estado["pesquisa"]
    assert pesquisa.perguntas == ["Por que o lucro caiu?", "Houve impairment?"]
    assert pesquisa.historico == "Net Income 4T25: -3.8B"

    fx = gerar.montar_fixture("VALE3", estado, passagens, "m", "t")
    assert fx["pesquisa"] == pesquisa.model_dump()
    assert [a["texto"] for a in fx["pesquisa"]["achados"]] == [
        "achado: Por que o lucro caiu?\nFontes: vale.com", "achado: Houve impairment?\nFontes: vale.com"]
    assert json.loads(json.dumps(fx, ensure_ascii=False)) == fx


def test_coletar_ramos_paralelos_intercalados():
    """Confere que eventos intercalados de Analyzer e Investigator no paralelo separam as tools por agente."""
    eventos = [
        (("YFinance:yf-1",), "updates", {"tools": {"messages": [ToolMessage("dados", name="buscar_dados_acao_b3", tool_call_id="1")]}}),
        (("Analyzer:ana-1",), "updates", {"tools": {"messages": [ToolMessage("noticias", name="buscar_noticias_web", tool_call_id="2")]}}),
        (("Investigator:inv-1",), "updates", {"tools": {"messages": [ToolMessage("fatos", name="buscar_historico_trimestral", tool_call_id="3")]}}),
        (("Analyzer:ana-1",), "updates", {"tools": {"messages": [ToolMessage("setor", name="buscar_noticias_web", tool_call_id="4")]}}),
        ((), "values", {"messages": [HumanMessage("fim", name="Consolidador")], "relatorio": REL}),
    ]
    estado, passagens = gerar.coletar(eventos)
    assert len(passagens) == 3
    por_agente = {p["agente"]: p for p in passagens}
    assert [t["conteudo"] for t in por_agente["Analyzer"]["tools"]] == ["noticias", "setor"]
    assert [t["conteudo"] for t in por_agente["Investigator"]["tools"]] == ["fatos"]
    assert [t["conteudo"] for t in por_agente["YFinance"]["tools"]] == ["dados"]


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
    assert fx["pesquisa"] is None  # análise sem Investigator
    assert fx["busca"] == "google"  # padrão de montar_fixture
    assert json.loads(json.dumps(fx, ensure_ascii=False)) == fx


def test_montar_fixture_guarda_a_pesquisa():
    """Confere que a pesquisa do subgrafo (perguntas, achados, voltas e histórico trimestral) vai para a fixture."""
    pesquisa = PesquisaFeita(perguntas=["p1"], achados=[{"pergunta": "p1", "rodada": 1, "texto": "t1"}],
                             voltas=1, historico="Net Income 1.25B")
    estado = {"messages": [], "relatorio": REL, "sinais_anomalia": [], "pesquisa": pesquisa}
    fx = gerar.montar_fixture("VALE3", estado, [], "m", "t")
    assert fx["pesquisa"] == {"perguntas": ["p1"], "achados": [{"pergunta": "p1", "rodada": 1, "texto": "t1"}],
                              "voltas": 1, "historico": "Net Income 1.25B"}


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


def test_main_com_tavily_grava_com_sufixo_e_nao_toca_a_do_google(tmp_path):
    """Confere que, com a busca na Tavily, a fixture vai para <ticker>_tavily.json com o provedor anotado,
    e a do Google (<ticker>.json) fica como estava."""
    do_google = tmp_path / "vale3.json"
    do_google.write_text('{"busca": "google"}', encoding="utf-8")
    eventos = [((), "values", {"messages": [HumanMessage("Analise a ação VALE3"), HumanMessage("# Relatório", name="Consolidador")],
                               "relatorio": REL, "sinais_anomalia": []})]
    with patch.object(gerar, "app") as app_falso, patch.object(gerar, "BUSCA_PROVEDOR", "tavily"), \
         patch("fluxo_financeiro.tools.web_search.provedor_da_busca", return_value="tavily"):
        app_falso.stream.return_value = iter(eventos)
        assert gerar.main(["VALE3"], pasta=tmp_path) == 0
    assert json.loads((tmp_path / "vale3_tavily.json").read_text(encoding="utf-8"))["busca"] == "tavily"
    assert do_google.read_text(encoding="utf-8") == '{"busca": "google"}'


def test_main_recusa_quando_a_tavily_caiu_no_google_sem_rodar(tmp_path, capsys):
    """Confere que BUSCA_PROVEDOR=tavily com a busca caindo no Google (sem chave) sai com 1 antes de gastar,
    em vez de gravar uma fixture do Google por cima da que já existe."""
    with patch.object(gerar, "rodar") as rodar_falso, patch.object(gerar, "BUSCA_PROVEDOR", "tavily"), \
         patch("fluxo_financeiro.tools.web_search.provedor_da_busca", return_value="google"):
        assert gerar.main(["VALE3"], pasta=tmp_path) == 1
        rodar_falso.assert_not_called()
    assert "tavily" in capsys.readouterr().out
    assert not list(tmp_path.glob("*.json"))


def test_main_nao_grava_quando_relatorio_ausente(tmp_path):
    """Confere que, com o Consolidador no fallback, main sai com 1 e não deixa arquivo."""
    with patch.object(gerar, "app") as app_falso:
        app_falso.stream.return_value = iter([((), "values", {"messages": [], "relatorio": None, "sinais_anomalia": []})])
        assert gerar.main(["VALE3"], pasta=tmp_path) == 1
    assert not list(tmp_path.glob("*.json"))


def test_main_recusa_ticker_inexistente_sem_rodar(_ticker_existe, tmp_path, capsys):
    """Confere que o ticker que a Brapi diz não existir sai com 2, com a mensagem, sem rodar a análise."""
    existe, _ = _ticker_existe
    existe.return_value = False
    with patch.object(gerar, "rodar") as rodar_falso:
        assert gerar.main(["XXXX3"], pasta=tmp_path) == 2
        rodar_falso.assert_not_called()
    assert "Ticker não encontrado na B3: XXXX3." in capsys.readouterr().out
    assert not list(tmp_path.glob("*.json"))
