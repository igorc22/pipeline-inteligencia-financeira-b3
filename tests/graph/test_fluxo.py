"""Testes do grafo inteiro (Supervisor + nós + router), com agentes e LLM mockados.

Os testes de test_supervisor.py olham uma decisão por vez; aqui o app compilado roda do START ao
END, e conferimos o caminho percorrido: é o mesmo que o scripts/e2e.py valida com APIs reais.
"""
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from fluxo_financeiro.agents.analysts import SECAO_NOTICIAS, SECAO_SETOR
from fluxo_financeiro.agents.consolidator import (
    LIMITACAO_PERFIL_RESERVA,
    LIMITACAO_SEM_DADOS,
    LIMITACAO_SEM_NOTICIAS,
    LIMITACAO_SEM_SETOR,
)
from fluxo_financeiro.graph.graph import app
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
from fluxo_financeiro.tools.financial_data import AVISO_PERFIL_RESERVA

WORKERS = {"YFinance", "Analyzer", "Investigator"}
RELATORIO = RelatorioFinal(resumo="Resumo da análise.", indicadores=["P/L: 74,7x"], contexto="notícias",
                           riscos=["minério"], limitacoes=[])
BLOCO_BCB = ("INDICADORES ECONÔMICOS (Banco Central, buscados em código):\n"
             "- SELIC (meta): 13.75% a.a. (BCB, 08/12/2026)")
# O Analyzer responde numa passagem só, com as duas seções (notícias da empresa e setor).
RESPOSTA_ANALYZER = f"{SECAO_NOTICIAS}\nanálise de notícias\n\n{SECAO_SETOR}\nanálise do setor"


def _agente(texto):
    agente = MagicMock()
    agente.invoke.return_value = {"messages": [AIMessage(content=texto)]}
    return agente


DIAGNOSTICO = "- Causa identificada: prejuízo no 4T25"
PESQUISA = PesquisaFeita(perguntas=["Por que o lucro caiu?"],
                         achados=[{"pergunta": "Por que o lucro caiu?", "rodada": 1, "texto": "impairment"}],
                         voltas=0, historico="Net Income 1.25B")


def _investigar_falso():
    """O subgrafo de pesquisa trocado por um falso: `invoke` é a função `investigar(tarefa, ticker)`.

    O atributo se chama invoke para os testes tratarem os 3 workers igual (call_count, side_effect).
    """
    investigador = MagicMock()
    investigador.invoke.return_value = (DIAGNOSTICO, PESQUISA)
    return investigador


def _decisao(proximo, tarefa=None):
    return RouteDecision(reasoning=f"vai para {proximo}", next_agent=proximo, task_for_agent=tarefa)


@pytest.fixture
def grafo_mockado():
    """Troca os agentes do YFinance e do Analyzer, o subgrafo do Investigator (`investigar`), o detector
    de anomalias e o LLM do Supervisor por mocks.

    O detector por padrão não acha nada (o LLM decide a Etapa 4); cada teste pode trocar o
    return_value de mocks["sinais"]. Sem esse mock, o nó do YFinance iria ao yfinance de verdade.
    O LLM do Consolidador também é mockado (mocks["consolidador"]): sem ele, todo teste daqui
    chamaria o Gemini de verdade no fim do fluxo. O bloco do Banco Central (mocks["indicadores"])
    devolve BLOCO_BCB: sem esse mock, o nó do YFinance iria à API do BCB.
    """
    mocks = {
        "YFinance": _agente("Dados para VALE3.SA: P/L 74.7x, ROE 0.3%"),
        "Analyzer": _agente(RESPOSTA_ANALYZER),
        "Investigator": _investigar_falso(),
    }
    with patch("fluxo_financeiro.graph.graph.yfinance_agent", mocks["YFinance"]), \
         patch("fluxo_financeiro.graph.graph.analyzer_agent", mocks["Analyzer"]), \
         patch("fluxo_financeiro.graph.graph.investigar", mocks["Investigator"].invoke), \
         patch("fluxo_financeiro.graph.graph.detectar_sinais_anomalia", return_value=[]) as sinais, \
         patch("fluxo_financeiro.graph.graph.indicadores_economicos_em_texto", return_value=BLOCO_BCB) as indicadores, \
         patch("fluxo_financeiro.graph.supervisor.llm") as llm, \
         patch("fluxo_financeiro.agents.consolidator.llm") as llm_consolidador:
        llm_consolidador.with_structured_output.return_value.invoke.return_value = RELATORIO
        mocks["consolidador"] = llm_consolidador
        mocks["sinais"] = sinais
        mocks["indicadores"] = indicadores
        mocks["decisoes"] = llm.with_structured_output.return_value.invoke
        yield mocks


def _rodar():
    return app.invoke({"messages": [HumanMessage(content="Analise a ação VALE3")]})


def _quem_falou(resultado):
    return [m.name for m in resultado["messages"] if m.name in WORKERS]


def test_vale3_roda_analista_e_investigator_em_paralelo(grafo_mockado):
    """Confere que, na análise da VALE3 com sinais de anomalia, o Analista e o Investigator rodam em paralelo (1 chamada cada), o Supervisor roda 3 vezes até FINISH, loop_count é 3 e os campos noticias, contexto_setor e diagnostico são preenchidos."""
    queda = SinalAnomalia(tipo="queda_lucro", descricao="O lucro líquido de VALE3.SA caiu 35% contra o ano anterior.")
    grafo_mockado["sinais"].return_value = [queda]
    grafo_mockado["decisoes"].side_effect = [
        _decisao("YFinance", "Colete os dados da VALE3"),
    ]

    resultado = _rodar()

    assert _quem_falou(resultado) == ["YFinance", "Analyzer", "Investigator"]
    assert grafo_mockado["Analyzer"].invoke.call_count == 1
    assert grafo_mockado["Investigator"].invoke.call_count == 1
    assert resultado["loop_count"] == 3
    assert grafo_mockado["decisoes"].call_count == 1
    assert resultado["noticias"] == "análise de notícias"
    assert resultado["contexto_setor"] == "análise do setor"
    assert resultado["diagnostico"] == "- Causa identificada: prejuízo no 4T25"
    assert resultado["pesquisa"] == PESQUISA
    assert resultado["messages"][-1].name == "Consolidador"
    assert resultado["decidido_por"] == "guard"


def _subgrafo_falso(perguntas_ou_erros):
    """Subgrafo de pesquisa de verdade com o LLM falso: a fila de PerguntasPesquisa vem do teste
    (exceções no começo imitam o LLM fora do ar), a síntese e o crítico respondem uma vez."""
    return criar_grafo_pesquisa(LlmFalso({
        PerguntasPesquisa: perguntas_ou_erros,
        DiagnosticoPesquisa: [DiagnosticoPesquisa(causa="impairment de US$ 1 bi no 4T25", natureza="pontual",
                                                  evidencias=["baixa contábil"], impacto="lucro recorrente intacto")],
        CriticaPesquisa: [CriticaPesquisa(aprovado=True, lacunas=[])],
    }))


@pytest.fixture
def subgrafo_real(grafo_mockado):
    """Desfaz o falso do `investigar` do grafo_mockado: o nó do Investigator roda o subgrafo de verdade.

    Só a busca e o histórico trimestral ficam mockados (sem rede); o LLM do subgrafo é o LlmFalso
    que cada teste instala em fluxo_financeiro.agents.pesquisa.grafo_pesquisa.
    """
    from fluxo_financeiro.agents import pesquisa
    with patch("fluxo_financeiro.graph.graph.investigar", pesquisa.investigar), \
         patch("fluxo_financeiro.agents.pesquisa.pesquisar_pergunta",
               side_effect=lambda p, t: f"achado sobre {p}\nFontes: vale.com") as busca, \
         patch("fluxo_financeiro.agents.pesquisa.buscar_historico_trimestral") as historico:
        historico.invoke.return_value = "Net Income 4T25: -3.8B"
        grafo_mockado["busca"] = busca
        grafo_mockado["historico"] = historico
        yield grafo_mockado


def test_vale3_paralelo_com_o_subgrafo(subgrafo_real):
    """Confere que, com o subgrafo de pesquisa de verdade dentro do ramo do Investigator, o paralelo da 7a
    continua (Analista e Investigator no mesmo passo, loop_count 3) e o state ganha a pesquisa e o diagnóstico."""
    subgrafo_real["sinais"].return_value = [QUEDA]
    subgrafo_real["decisoes"].side_effect = [_decisao("YFinance", "Colete os dados da VALE3")]
    perguntas = ["Por que o lucro da Vale caiu no 4T25?", "Houve impairment na Vale?"]

    with patch("fluxo_financeiro.agents.pesquisa.grafo_pesquisa", _subgrafo_falso([PerguntasPesquisa(perguntas=perguntas)])):
        resultado = _rodar()

    assert _quem_falou(resultado) == ["YFinance", "Analyzer", "Investigator"]
    assert resultado["loop_count"] == 3
    assert resultado["decidido_por"] == "guard"
    assert subgrafo_real["Analyzer"].invoke.call_count == 1
    pesquisa = resultado["pesquisa"]
    assert pesquisa.perguntas == perguntas
    assert [a["pergunta"] for a in pesquisa.achados] == perguntas
    assert pesquisa.historico == "Net Income 4T25: -3.8B"
    subgrafo_real["historico"].invoke.assert_called_once_with("VALE3")
    # A tarefa do Supervisor (a dos sinais) é o que o subgrafo investiga, com o ticker do pedido.
    assert {c.args[1] for c in subgrafo_real["busca"].call_args_list} == {"VALE3"}
    diagnostico = resultado["diagnostico"]
    for secao in ("- Causa identificada:", "- Natureza do evento: pontual", "- Evidências:", "- Impacto no investimento:"):
        assert secao in diagnostico
    assert diagnostico.endswith("Fontes: vale.com")
    assert resultado["relatorio"].diagnostico == diagnostico
    assert next(m for m in resultado["messages"] if m.name == "Investigator").content == diagnostico


def test_excecao_no_subgrafo_vira_erro_do_investigator(subgrafo_real):
    """Confere que o LLM do subgrafo fora do ar vira erro do Investigator pelo retry do nó (2 tentativas
    locais) e que o reenvio do coordenador roda o subgrafo inteiro de novo, do histórico ao crítico."""
    subgrafo_real["sinais"].return_value = [QUEDA]
    subgrafo_real["decisoes"].side_effect = [_decisao("YFinance", "Colete os dados da VALE3")]
    fila = [TimeoutError("LLM fora"), TimeoutError("LLM fora"), PerguntasPesquisa(perguntas=["Por que o lucro caiu?"])]

    with patch("fluxo_financeiro.agents.pesquisa.grafo_pesquisa", _subgrafo_falso(fila)):
        resultado = _rodar()

    # 3 rodadas do subgrafo inteiro: as 2 locais que falharam e a do reenvio.
    assert subgrafo_real["historico"].invoke.call_count == 3
    assert subgrafo_real["busca"].call_count == 1
    erros_no_historico = [m for m in resultado["messages"]
                          if m.name == "Investigator" and m.content.startswith("Erro: Investigator falhou depois de 2 tentativas")]
    assert len(erros_no_historico) == 1
    assert resultado["erros"]["Investigator"] is None
    assert resultado["tentativas"]["Investigator"] == 0
    assert resultado["diagnostico"].startswith("- Causa identificada: impairment")
    assert resultado["pesquisa"].perguntas == ["Por que o lucro caiu?"]
    assert resultado["loop_count"] == 3  # o reenvio não conta loop, como em test_falha_num_ramo_reenvia_so_ele
    assert subgrafo_real["Analyzer"].invoke.call_count == 1


def test_cada_ramo_recebe_so_a_propria_tarefa(grafo_mockado):
    """Confere que, na execução em paralelo, cada ramo recebe apenas a própria tarefa do Supervisor, sem ver a tarefa do outro ramo."""
    queda = SinalAnomalia(tipo="queda_lucro", descricao="O lucro líquido de VALE3.SA caiu 35% contra o ano anterior.")
    grafo_mockado["sinais"].return_value = [queda]
    grafo_mockado["decisoes"].side_effect = [
        _decisao("YFinance", "Colete os dados da VALE3"),
    ]

    _rodar()

    historico_ana = grafo_mockado["Analyzer"].invoke.call_args.args[0]["messages"]
    assert historico_ana[-1].name == "Supervisor"
    assert SECAO_NOTICIAS in historico_ana[-1].content and SECAO_SETOR in historico_ana[-1].content
    assert not any("Investigue as anomalias" in m.content for m in historico_ana)

    tarefa_inv, ticker = grafo_mockado["Investigator"].invoke.call_args.args
    assert "Investigue as anomalias" in tarefa_inv
    assert SECAO_NOTICIAS not in tarefa_inv
    assert ticker == "VALE3"


def test_llm_sem_sinal_ainda_pode_investigar(grafo_mockado):
    """Confere que, sem sinal de anomalia em código, o LLM na Etapa 4 ainda pode acionar o Investigator sequencialmente após o Analyzer."""
    grafo_mockado["sinais"].return_value = []
    grafo_mockado["decisoes"].side_effect = [
        _decisao("YFinance", "Colete os dados da VALE3"),
        _decisao("Investigator", "Investigue o ROE de 0,3% da VALE3"),
    ]

    resultado = _rodar()

    assert _quem_falou(resultado) == ["YFinance", "Analyzer", "Investigator"]
    assert grafo_mockado["Analyzer"].invoke.call_count == 1
    assert grafo_mockado["Investigator"].invoke.call_count == 1
    assert resultado["loop_count"] == 4
    assert grafo_mockado["decisoes"].call_count == 2
    assert resultado["diagnostico"] == "- Causa identificada: prejuízo no 4T25"
    assert resultado["relatorio"].diagnostico == "- Causa identificada: prejuízo no 4T25"
    assert grafo_mockado["Investigator"].invoke.call_args.args == ("Investigue o ROE de 0,3% da VALE3", "VALE3")
    msg_yfinance = next(m for m in resultado["messages"] if m.name == "YFinance")
    assert resultado["dados_mercado"] == msg_yfinance.content
    assert resultado["noticias"] == "análise de notícias"
    assert resultado["contexto_setor"] == "análise do setor"


def _yfinance_com_saida_da_tool(saida_da_tool, resposta_final):
    """Agente do YFinance falso cuja resposta final pode ter perdido a linha "Fonte:" da tool.

    Como o create_agent, devolve o histórico recebido seguido das mensagens novas.
    """
    agente = MagicMock()
    agente.invoke.side_effect = lambda entrada: {"messages": [
        *entrada["messages"],
        ToolMessage(content=saida_da_tool, tool_call_id="1", name="buscar_dados_acao_b3"),
        AIMessage(content=resposta_final),
    ]}
    return agente


def test_aviso_da_reserva_chega_ao_relatorio_mesmo_se_o_agente_resumir(grafo_mockado):
    """Confere que o aviso da reserva vai para a mensagem e para as limitações mesmo que o LLM do YFinance o omita."""
    grafo_mockado["decisoes"].side_effect = [_decisao("YFinance", "Colete os dados da VALE3"), _decisao("FINISH")]
    agente = _yfinance_com_saida_da_tool(f"Dados para VALE3.SA: P/L 74.7x\n{AVISO_PERFIL_RESERVA}\n",
                                         "Dados para VALE3.SA: P/L 74.7x")

    with patch("fluxo_financeiro.graph.graph.yfinance_agent", agente):
        resultado = _rodar()

    msg_yfinance = next(m for m in resultado["messages"] if m.name == "YFinance")
    assert msg_yfinance.text.count(AVISO_PERFIL_RESERVA) == 1
    assert LIMITACAO_PERFIL_RESERVA in resultado["relatorio"].limitacoes


def test_aviso_da_reserva_nao_repete_nem_aparece_com_a_brapi(grafo_mockado):
    """Confere que o aviso não é duplicado quando o agente já o repassou, nem acrescentado quando a Brapi respondeu."""
    grafo_mockado["decisoes"].side_effect = [_decisao("YFinance", "Colete os dados da VALE3"), _decisao("FINISH")] * 2
    copiado = f"Dados para VALE3.SA: P/L 74.7x\n{AVISO_PERFIL_RESERVA}"
    with patch("fluxo_financeiro.graph.graph.yfinance_agent", _yfinance_com_saida_da_tool(copiado, copiado)):
        resultado = _rodar()
    msg_yfinance = next(m for m in resultado["messages"] if m.name == "YFinance")
    assert msg_yfinance.text.count(AVISO_PERFIL_RESERVA) == 1

    com_brapi = "Dados para VALE3.SA: P/L 74.7x\nFonte: cotação e perfil da Brapi; P/L, ROE, DY e histórico do yfinance."
    with patch("fluxo_financeiro.graph.graph.yfinance_agent", _yfinance_com_saida_da_tool(com_brapi, "P/L 74.7x")):
        resultado = _rodar()
    msg_yfinance = next(m for m in resultado["messages"] if m.name == "YFinance")
    assert AVISO_PERFIL_RESERVA not in msg_yfinance.text
    assert LIMITACAO_PERFIL_RESERVA not in resultado["relatorio"].limitacoes


def test_yfinance_anexa_indicadores(grafo_mockado):
    """Confere que a mensagem do YFinance termina com o bloco do Banco Central, depois dos sinais de anomalia."""
    grafo_mockado["sinais"].return_value = [SinalAnomalia(tipo="prejuizo", descricao="prejuízo no trimestre")]
    grafo_mockado["decisoes"].side_effect = [_decisao("YFinance", "Colete os dados da VALE3")]

    resultado = _rodar()

    msg_yfinance = next(m for m in resultado["messages"] if m.name == "YFinance")
    assert msg_yfinance.text.endswith("\n\n" + BLOCO_BCB)
    assert msg_yfinance.text.index("SINAIS DE ANOMALIA") < msg_yfinance.text.index("INDICADORES ECONÔMICOS")
    grafo_mockado["indicadores"].assert_called_once_with()


def test_yfinance_sem_indicadores_nao_anexa(grafo_mockado):
    """Confere que, com o BCB fora do ar (bloco vazio), a mensagem do YFinance segue sem o bloco."""
    grafo_mockado["indicadores"].return_value = ""
    grafo_mockado["decisoes"].side_effect = [_decisao("YFinance", "Colete os dados da VALE3"), _decisao("FINISH")]

    resultado = _rodar()

    msg_yfinance = next(m for m in resultado["messages"] if m.name == "YFinance")
    assert "INDICADORES ECONÔMICOS" not in msg_yfinance.text
    assert msg_yfinance.text == "Dados para VALE3.SA: P/L 74.7x, ROE 0.3%"
    assert resultado["messages"][-1].name == "Consolidador"


def test_wege3_sem_sinal_nao_usa_paralelo(grafo_mockado):
    """Confere que, sem sinal de anomalia (WEGE3), o fluxo não usa o paralelo, o Analyzer roda sozinho, o LLM escolhe FINISH e o Investigator nunca é acionado."""
    grafo_mockado["decisoes"].side_effect = [
        _decisao("YFinance", "Colete os dados da WEGE3"),
        _decisao("FINISH"),
    ]

    resultado = _rodar()

    assert _quem_falou(resultado) == ["YFinance", "Analyzer"]
    assert grafo_mockado["Analyzer"].invoke.call_count == 1
    assert resultado["messages"][-1].name == "Consolidador"
    assert resultado["relatorio"].diagnostico is None
    assert resultado["loop_count"] == 3
    grafo_mockado["Investigator"].invoke.assert_not_called()
    assert resultado.get("diagnostico") is None
    assert resultado["noticias"] == "análise de notícias"
    assert resultado["contexto_setor"] == "análise do setor"
    assert resultado["dados_mercado"]
    # A tarefa única do Analyzer pede as duas seções
    tarefa = grafo_mockado["Analyzer"].invoke.call_args.args[0]["messages"][-1]
    assert tarefa.name == "Supervisor"
    assert SECAO_NOTICIAS in tarefa.content and SECAO_SETOR in tarefa.content


def test_analyzer_sem_secao_do_setor_registra_a_limitacao(grafo_mockado):
    """Confere que, com a resposta do Analyzer sem as seções, o texto vai para noticias, o Analyzer não roda de novo e o relatório anota o setor que faltou."""
    grafo_mockado["Analyzer"].invoke.return_value = {"messages": [AIMessage(content="análise de notícias")]}
    grafo_mockado["decisoes"].side_effect = [_decisao("YFinance", "Colete os dados da WEGE3"), _decisao("FINISH")]

    resultado = _rodar()

    assert grafo_mockado["Analyzer"].invoke.call_count == 1
    assert resultado["noticias"] == "análise de notícias"
    assert resultado.get("contexto_setor") is None
    assert LIMITACAO_SEM_SETOR in resultado["relatorio"].limitacoes
    assert resultado["loop_count"] == 3


def test_hard_stop_segura_llm_que_nunca_encerra(grafo_mockado):
    """Confere que o hard stop (loop_count >= 6) encerra o grafo quando o LLM nunca escolhe FINISH."""
    grafo_mockado["decisoes"].return_value = _decisao("Analyzer", "Busque mais notícias")

    resultado = _rodar()
    assert resultado["decidido_por"] == "hard_stop"

    assert resultado["loop_count"] == 7  # 6 passagens + a do hard stop
    assert len(_quem_falou(resultado)) == 6
    assert resultado["messages"][-1].name == "Consolidador"  # o hard stop também consolida
    # O YFinance nunca rodou (o LLM só mandou o Analyzer): sem dados_mercado, o relatório diz isso.
    assert resultado.get("dados_mercado") is None
    assert LIMITACAO_SEM_DADOS in resultado["relatorio"].limitacoes
    assert resultado["relatorio"].indicadores == []


# ---------------------------------------------------------------------------
# Retry em camadas: o nó repete localmente, o coordenador reenvia uma vez ou segue sem o agente
# ---------------------------------------------------------------------------

QUEDA = SinalAnomalia(tipo="queda_lucro", descricao="O lucro líquido de VALE3.SA caiu 35% contra o ano anterior.")


def test_falha_num_ramo_reenvia_so_ele(grafo_mockado):
    """Confere que, quando um ramo do paralelo falha, o coordenador reenvia apenas o agente que falhou sem rodar o outro de novo, chegando a FINISH pelo guard com loop_count 3."""
    grafo_mockado["sinais"].return_value = [QUEDA]
    grafo_mockado["decisoes"].side_effect = [_decisao("YFinance", "Colete os dados da VALE3")]
    resposta = (DIAGNOSTICO, PESQUISA)
    # As 2 tentativas locais da 1ª rodada falham; a 2ª rodada (mandada pelo coordenador) acerta.
    grafo_mockado["Investigator"].invoke.side_effect = [TimeoutError("lento"), TimeoutError("lento"), resposta]

    resultado = _rodar()

    assert grafo_mockado["Analyzer"].invoke.call_count == 1
    assert grafo_mockado["Investigator"].invoke.call_count == 3
    assert resultado["loop_count"] == 3
    assert resultado["decidido_por"] == "guard"
    assert resultado["diagnostico"] == "- Causa identificada: prejuízo no 4T25"
    assert resultado["noticias"] == "análise de notícias"
    assert resultado["relatorio"].diagnostico == "- Causa identificada: prejuízo no 4T25"
    assert resultado["erros"]["Investigator"] is None
    assert resultado["tentativas"]["Investigator"] == 0
    assert not any("falhou depois de" in l for l in resultado["relatorio"].limitacoes)


def test_analyzer_permanente_segue_sem_noticias(grafo_mockado):
    """Confere que o Analyzer com erro permanente roda uma vez só e o relatório registra a etapa que ficou de fora."""
    grafo_mockado["decisoes"].side_effect = [_decisao("YFinance", "Colete os dados da VALE3"), _decisao("FINISH")]
    grafo_mockado["Analyzer"].invoke.side_effect = ValueError("chave inválida")

    resultado = _rodar()

    assert grafo_mockado["Analyzer"].invoke.call_count == 1
    assert resultado.get("noticias") is None and resultado.get("contexto_setor") is None
    assert resultado["erros"]["Analyzer"].tipo == "permanente"
    limitacoes = resultado["relatorio"].limitacoes
    assert "O Analyzer falhou depois de 1 tentativa (erro permanente): a etapa ficou de fora." in limitacoes
    assert LIMITACAO_SEM_NOTICIAS in limitacoes
    assert resultado["loop_count"] == 3  # YFinance, Analyzer e a Etapa 4 pelo LLM


@pytest.mark.parametrize("worker", sorted(WORKERS))
@pytest.mark.parametrize("excecao", [TimeoutError("lento"), RuntimeError("quebrou")], ids=["temporario", "permanente"])
def test_excecao_no_agente_nao_derruba_a_analise(grafo_mockado, worker, excecao):
    """Confere que uma exceção em qualquer worker, sempre, não derruba o grafo: a análise chega ao Consolidador."""
    grafo_mockado["sinais"].return_value = [QUEDA]  # com sinais, o Investigator roda pelo guard
    grafo_mockado["decisoes"].side_effect = [_decisao("YFinance", "Colete os dados da VALE3"), _decisao("FINISH")]
    grafo_mockado[worker].invoke.side_effect = excecao

    resultado = _rodar()

    assert resultado["messages"][-1].name == "Consolidador"
    assert resultado["relatorio"] is not None
    assert resultado["decidido_por"] == "guard"
    erro = resultado["erros"][worker]
    temporario = isinstance(excecao, TimeoutError)
    assert erro.tipo == ("transitorio" if temporario else "permanente")
    # Temporário: 2 rodadas do nó (a local e a do coordenador), 2 tentativas cada. Permanente: 1 chamada.
    assert grafo_mockado[worker].invoke.call_count == (4 if temporario else 1)
    assert any(l.startswith(f"O {worker} falhou depois de") for l in resultado["relatorio"].limitacoes)


def test_falha_do_consolidador_nao_perde_a_analise(grafo_mockado):
    """Confere que, com erro no LLM do Consolidador, a resposta final vira a junção das respostas dos agentes."""
    grafo_mockado["decisoes"].side_effect = [
        _decisao("YFinance", "Colete os dados da VALE3"),
        _decisao("FINISH"),
    ]
    grafo_mockado["consolidador"].with_structured_output.return_value.invoke.side_effect = Exception("429")

    resultado = _rodar()

    assert _quem_falou(resultado) == ["YFinance", "Analyzer"]
    final = resultado["messages"][-1]
    assert final.name == "Consolidador"
    assert "análise de notícias" in final.content and "P/L 74.7x" in final.content
    assert resultado["relatorio"] is None
