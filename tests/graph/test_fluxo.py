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
from fluxo_financeiro.shared.types import RelatorioFinal, RouteDecision, SinalAnomalia
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


def _decisao(proximo, tarefa=None):
    return RouteDecision(reasoning=f"vai para {proximo}", next_agent=proximo, task_for_agent=tarefa)


@pytest.fixture
def grafo_mockado():
    """Troca os 3 agentes, o detector de anomalias e o LLM do Supervisor por mocks.

    O detector por padrão não acha nada (o LLM decide a Etapa 4); cada teste pode trocar o
    return_value de mocks["sinais"]. Sem esse mock, o nó do YFinance iria ao yfinance de verdade.
    O LLM do Consolidador também é mockado (mocks["consolidador"]): sem ele, todo teste daqui
    chamaria o Gemini de verdade no fim do fluxo. O bloco do Banco Central (mocks["indicadores"])
    devolve BLOCO_BCB: sem esse mock, o nó do YFinance iria à API do BCB.
    """
    mocks = {
        "YFinance": _agente("Dados para VALE3.SA: P/L 74.7x, ROE 0.3%"),
        "Analyzer": _agente(RESPOSTA_ANALYZER),
        "Investigator": _agente("- Causa identificada: prejuízo no 4T25"),
    }
    with patch("fluxo_financeiro.graph.graph.yfinance_agent", mocks["YFinance"]), \
         patch("fluxo_financeiro.graph.graph.analyzer_agent", mocks["Analyzer"]), \
         patch("fluxo_financeiro.graph.graph.investigator_agent", mocks["Investigator"]), \
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


def test_sinal_em_codigo_aciona_investigator_sem_llm(grafo_mockado):
    """Confere que, com sinal de anomalia calculado em código, a Etapa 4 vai para o Investigator pelo guard."""
    queda = SinalAnomalia(tipo="queda_lucro", descricao="O lucro líquido de VALE3.SA caiu 35% contra o ano anterior.")
    grafo_mockado["sinais"].return_value = [queda]
    grafo_mockado["decisoes"].side_effect = [
        _decisao("YFinance", "Colete os dados da VALE3"),
    ]

    resultado = _rodar()

    assert _quem_falou(resultado) == ["YFinance", "Analyzer", "Investigator"]
    assert resultado["messages"][-1].name == "Consolidador"
    assert resultado["loop_count"] == 4
    grafo_mockado["sinais"].assert_called_once_with("VALE3")  # ticker extraído do pedido
    # Etapas 2 e 4 e o FINISH final são guards: o LLM só decide a etapa 1
    assert grafo_mockado["decisoes"].call_count == 1
    # O sinal aparece na mensagem do YFinance e vira a tarefa do Investigator
    msg_yfinance = next(m for m in resultado["messages"] if m.name == "YFinance")
    assert "SINAIS DE ANOMALIA" in msg_yfinance.content
    tarefa = grafo_mockado["Investigator"].invoke.call_args.args[0]["messages"][-1]
    assert tarefa.name == "Supervisor"
    assert queda.descricao in tarefa.content


def test_llm_pode_acionar_investigator_mesmo_sem_sinal(grafo_mockado):
    """Confere que, sem sinal calculado, o LLM ainda pode mandar investigar (Etapa 4 pelo LLM)."""
    grafo_mockado["decisoes"].side_effect = [
        _decisao("YFinance", "Colete os dados da VALE3"),
        _decisao("Investigator", "Investigue o ROE de 0,3% da VALE3"),
    ]

    resultado = _rodar()

    assert _quem_falou(resultado) == ["YFinance", "Analyzer", "Investigator"]
    final = resultado["messages"][-1]
    assert final.name == "Consolidador"
    assert "- Causa identificada: prejuízo no 4T25" in final.content  # diagnóstico copiado
    assert resultado["relatorio"].diagnostico == "- Causa identificada: prejuízo no 4T25"
    assert resultado["loop_count"] == 4
    # Só 2 decisões passam pelo LLM (etapas 1 e 4): a etapa 2 e o FINISH final são guards
    assert grafo_mockado["decisoes"].call_count == 2
    # O Investigator recebe a tarefa do Supervisor como última mensagem do histórico
    historico = grafo_mockado["Investigator"].invoke.call_args.args[0]["messages"]
    assert historico[-1].name == "Supervisor"
    assert historico[-1].content == "Investigue o ROE de 0,3% da VALE3"
    # Cada agente gravou a própria saída num campo do state
    msg_yfinance = next(m for m in resultado["messages"] if m.name == "YFinance")
    assert resultado["dados_mercado"] == msg_yfinance.content
    assert resultado["noticias"] == "análise de notícias"
    assert resultado["contexto_setor"] == "análise do setor"
    assert resultado["diagnostico"] == "- Causa identificada: prejuízo no 4T25"


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


def test_fluxo_sem_anomalia_nao_chama_o_investigator(grafo_mockado):
    """Confere que, sem anomalia (a WEGE3), o Analyzer roda uma vez só e a etapa 4 vai direto para FINISH em 3 voltas."""
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


def test_falha_temporaria_no_investigator_nao_bate_no_hard_stop(grafo_mockado):
    """Confere que o reenvio do coordenador não conta volta: a VALE3 chega ao FINISH pelo guard, não pelo hard stop."""
    grafo_mockado["sinais"].return_value = [QUEDA]
    grafo_mockado["decisoes"].side_effect = [_decisao("YFinance", "Colete os dados da VALE3")]
    resposta = {"messages": [AIMessage(content="- Causa identificada: prejuízo no 4T25")]}
    # As 2 tentativas locais da 1ª rodada falham; a 2ª rodada (mandada pelo coordenador) acerta.
    grafo_mockado["Investigator"].invoke.side_effect = [TimeoutError("lento"), TimeoutError("lento"), resposta]

    resultado = _rodar()

    assert resultado["diagnostico"] == "- Causa identificada: prejuízo no 4T25"
    assert resultado["relatorio"].diagnostico == "- Causa identificada: prejuízo no 4T25"
    assert resultado["decidido_por"] == "guard"
    assert resultado["loop_count"] == 4
    assert grafo_mockado["Investigator"].invoke.call_count == 3
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
