"""Testes dos nós dos workers chamados direto: cada um grava a própria saída num campo do state.

Os agentes são mockados em fluxo_financeiro.graph.graph; no YFinance, o detector de anomalias e o
bloco do Banco Central também (sem eles, o nó iria ao yfinance e à API do BCB de verdade).
O retry local do nó usa a espera falsa da fixture `espera_falsa` (tests/conftest.py): nenhum teste dorme.
"""
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from fluxo_financeiro.graph.graph import analyzer_node, investigator_node, yfinance_node
from fluxo_financeiro.shared.types import ErroAgente, SinalAnomalia

PEDIDO = HumanMessage("Analise VALE3")


def _agente(texto):
    agente = MagicMock()
    agente.invoke.return_value = {"messages": [AIMessage(content=texto)]}
    return agente


def _rodar_analyzer(state, texto="análise de notícias"):
    with patch("fluxo_financeiro.graph.graph.analyzer_agent", _agente(texto)):
        return analyzer_node(state)


def test_yfinance_grava_dados_mercado():
    """Confere que o YFinance grava em dados_mercado o mesmo texto da mensagem, já com o bloco de sinais."""
    sinal = SinalAnomalia(tipo="prejuizo", descricao="prejuízo no trimestre")
    with patch("fluxo_financeiro.graph.graph.yfinance_agent", _agente("Dados para VALE3.SA: P/L 74.7x")), \
         patch("fluxo_financeiro.graph.graph.detectar_sinais_anomalia", return_value=[sinal]), \
         patch("fluxo_financeiro.graph.graph.indicadores_economicos_em_texto", return_value="INDICADORES ECONÔMICOS"):
        resultado = yfinance_node({"messages": [PEDIDO]})

    assert resultado["dados_mercado"] == resultado["messages"][0].content
    assert "SINAIS DE ANOMALIA" in resultado["dados_mercado"]
    assert "prejuízo no trimestre" in resultado["dados_mercado"]


def _agente_com_tools(texto_final, *saidas):
    """Agente falso no formato do create_agent: devolve o histórico recebido mais as mensagens novas."""
    chamada = AIMessage(content="", tool_calls=[
        {"name": f"tool_{i}", "args": {}, "id": str(i)} for i in range(len(saidas))
    ])
    tools = [ToolMessage(content=s, tool_call_id=str(i), name=f"tool_{i}") for i, s in enumerate(saidas)]
    agente = MagicMock()
    agente.invoke.side_effect = lambda entrada: {
        "messages": [*entrada["messages"], chamada, *tools, AIMessage(content=texto_final)]
    }
    return agente


def _rodar_yfinance(agente):
    with patch("fluxo_financeiro.graph.graph.yfinance_agent", agente), \
         patch("fluxo_financeiro.graph.graph.detectar_sinais_anomalia", return_value=[]), \
         patch("fluxo_financeiro.graph.graph.indicadores_economicos_em_texto", return_value="INDICADORES ECONÔMICOS"):
        return yfinance_node({"messages": [PEDIDO]})


def test_yfinance_resposta_vazia_usa_a_saida_das_tools(caplog):
    """Confere que, com a resposta final do agente vazia (aconteceu no e2e da VALE3), os dados vêm das tools, sem a tag."""
    dados = 'Dados para VALE3.SA:\nP/L:  77.2x\nSumario de Negócio:\n<conteudo_externo origem="brapi">\nA Vale minera.\n</conteudo_externo>'
    agente = _agente_com_tools("  \n", dados, "Piotroski F-Score para VALE3.SA: 5/9")

    with caplog.at_level("WARNING", logger="fluxo_financeiro"):
        resultado = _rodar_yfinance(agente)

    texto = resultado["dados_mercado"]
    assert texto == resultado["messages"][0].content
    assert texto.startswith("Dados para VALE3.SA:")
    assert "P/L:  77.2x" in texto and "Piotroski F-Score para VALE3.SA: 5/9" in texto
    assert "A Vale minera." in texto and "conteudo_externo" not in texto
    assert texto.endswith("INDICADORES ECONÔMICOS")
    assert any("resposta final vazia" in r.message for r in caplog.records)


def test_yfinance_sem_tools_vira_resposta_vazia():
    """Confere que, sem resposta e sem nenhuma tool, o nó repete o agente e, sem dados, devolve erro estruturado sem gravar dados_mercado."""
    agente = _agente_com_tools("")

    resultado = _rodar_yfinance(agente)

    assert agente.invoke.call_count == 2
    assert "dados_mercado" not in resultado
    erro = resultado["erros"]["YFinance"]
    assert erro.tipo == "transitorio" and "RespostaVazia" in erro.mensagem
    assert resultado["messages"][0].name == "YFinance"
    assert resultado["messages"][0].content.startswith("Erro:")


def test_yfinance_com_resposta_ignora_as_tools():
    """Confere que, com a resposta final preenchida, o texto do agente é usado e a saída crua das tools não entra."""
    resultado = _rodar_yfinance(_agente_com_tools("Resumo: P/L 77.2x", "saída crua da tool"))

    assert resultado["dados_mercado"].startswith("Resumo: P/L 77.2x")
    assert "saída crua da tool" not in resultado["dados_mercado"]


def test_analyzer_primeira_passagem_grava_noticias():
    """Confere que a primeira passagem do Analyzer grava em noticias e não toca em contexto_setor."""
    resultado = _rodar_analyzer({"messages": [PEDIDO], "dados_mercado": "dados"})

    assert resultado["noticias"] == "análise de notícias"
    assert "contexto_setor" not in resultado


def test_analyzer_segunda_grava_contexto_setor():
    """Confere que, com noticias já preenchido, o Analyzer grava em contexto_setor."""
    resultado = _rodar_analyzer({"messages": [PEDIDO], "noticias": "notícias da empresa"}, "contexto do setor")

    assert resultado["contexto_setor"] == "contexto do setor"
    assert "noticias" not in resultado


def test_analyzer_terceira_nao_sobrescreve_noticias():
    """Confere que uma terceira passagem do Analyzer vai para contexto_setor e deixa noticias como estava."""
    state = {"messages": [PEDIDO], "noticias": "notícias da empresa", "contexto_setor": "setor antigo"}

    resultado = _rodar_analyzer(state, "mais contexto")

    assert "noticias" not in resultado
    assert resultado["contexto_setor"] == "mais contexto"


def test_investigator_grava_diagnostico():
    """Confere que o Investigator grava a resposta em diagnostico."""
    with patch("fluxo_financeiro.graph.graph.investigator_agent", _agente("- Causa identificada: impairment")):
        resultado = investigator_node({"messages": [PEDIDO]})

    assert resultado["diagnostico"] == "- Causa identificada: impairment"
    assert resultado["messages"][0].name == "Investigator"


def test_no_grava_campo_mesmo_com_erro_em_texto():
    """Confere que uma resposta com o erro de uma tool em texto também é gravada, e a passagem seguinte vai para contexto_setor."""
    erro = _rodar_analyzer({"messages": [PEDIDO]}, "Erro ao buscar notícias: 429")
    assert erro["noticias"] == "Erro ao buscar notícias: 429"
    assert erro["erros"] == {"Analyzer": None}

    seguinte = _rodar_analyzer({"messages": [PEDIDO], "noticias": erro["noticias"]}, "contexto do setor")
    assert seguinte["contexto_setor"] == "contexto do setor"
    assert "noticias" not in seguinte


def _agente_em_sequencia(*resultados):
    """Agente falso que levanta ou responde, na ordem: exceção levanta, texto vira a resposta final."""
    agente = MagicMock()
    agente.invoke.side_effect = [
        r if isinstance(r, Exception) else {"messages": [AIMessage(content=r)]} for r in resultados
    ]
    return agente


def test_no_repete_localmente_e_acerta(espera_falsa):
    """Confere que uma falha temporária repete o agente no próprio nó, depois de 2 s, e a resposta é gravada sem erro."""
    agente = _agente_em_sequencia(TimeoutError("lento"), "notícias da empresa")

    with patch("fluxo_financeiro.graph.graph.analyzer_agent", agente):
        resultado = analyzer_node({"messages": [PEDIDO], "dados_mercado": "dados"})

    assert agente.invoke.call_count == 2
    espera_falsa.assert_called_once_with(2.0)
    assert resultado["noticias"] == "notícias da empresa"
    assert resultado["erros"] == {"Analyzer": None}
    assert resultado["tentativas"] == {"Analyzer": 0}


def test_no_esgota_e_devolve_erro_estruturado(caplog):
    """Confere que, esgotadas as 2 tentativas locais, o nó não levanta: devolve o erro estruturado e não grava o campo."""
    agente = _agente_em_sequencia(TimeoutError("lento"), TimeoutError("lento\nde novo"))

    with patch("fluxo_financeiro.graph.graph.investigator_agent", agente), \
         caplog.at_level("ERROR", logger="fluxo_financeiro"):
        resultado = investigator_node({"messages": [PEDIDO]})

    assert agente.invoke.call_count == 2
    assert "diagnostico" not in resultado
    erro = resultado["erros"]["Investigator"]
    assert erro.tipo == "transitorio"
    assert erro.tentativas == 1
    assert "\n" not in erro.mensagem
    assert resultado["tentativas"] == {"Investigator": 1}
    mensagem = resultado["messages"][0]
    assert mensagem.name == "Investigator"
    assert mensagem.content.startswith("Erro: Investigator falhou depois de 2 tentativas (transitorio)")
    linhas = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(linhas) == 1 and "\n" not in linhas[0].getMessage() and linhas[0].exc_info is None


def test_no_soma_as_tentativas_do_coordenador():
    """Confere que a contagem continua de onde estava: a rodada mandada pelo coordenador vira a tentativa 2."""
    agente = _agente_em_sequencia(TimeoutError(), TimeoutError())
    state = {"messages": [PEDIDO], "tentativas": {"Investigator": 1}}

    with patch("fluxo_financeiro.graph.graph.investigator_agent", agente):
        resultado = investigator_node(state)

    assert resultado["tentativas"] == {"Investigator": 2}
    assert resultado["erros"]["Investigator"].tentativas == 2


def test_no_permanente_nao_repete():
    """Confere que um erro permanente não repete o agente e sai como permanente, com a contagem real de tentativas."""
    agente = _agente_em_sequencia(ValueError("ticker não existe"), "não chega aqui")

    with patch("fluxo_financeiro.graph.graph.analyzer_agent", agente):
        resultado = analyzer_node({"messages": [PEDIDO]})

    assert agente.invoke.call_count == 1
    assert resultado["erros"]["Analyzer"].tipo == "permanente"
    assert "noticias" not in resultado
    assert resultado["messages"][0].content.startswith("Erro: Analyzer falhou depois de 1 tentativa (permanente)")


def test_mensagem_longa_e_cortada():
    """Confere que um erro com texto enorme (o do Gemini traz o JSON inteiro) é cortado em 300 caracteres em vez de derrubar o nó."""
    agente = _agente_em_sequencia(ValueError("x" * 5000))

    with patch("fluxo_financeiro.graph.graph.analyzer_agent", agente):
        resultado = analyzer_node({"messages": [PEDIDO]})

    assert len(resultado["erros"]["Analyzer"].mensagem) <= 300


def test_resposta_vazia_e_transitoria_e_repete():
    """Confere que uma resposta final vazia do agente conta como falha temporária e o nó repete o agente."""
    agente = _agente_em_sequencia("  ", "notícias da empresa")

    with patch("fluxo_financeiro.graph.graph.analyzer_agent", agente):
        resultado = analyzer_node({"messages": [PEDIDO]})

    assert agente.invoke.call_count == 2
    assert resultado["noticias"] == "notícias da empresa"


def test_sucesso_depois_de_falha_limpa_erro_e_tentativas():
    """Confere que o agente que acerta depois de ter falhado zera erro e tentativas, para a etapa seguinte ter o limite inteiro."""
    anterior = ErroAgente(tipo="transitorio", mensagem="TimeoutError: lento", tentativas=1)
    state = {"messages": [PEDIDO], "erros": {"Analyzer": anterior}, "tentativas": {"Analyzer": 1}}

    resultado = _rodar_analyzer(state)

    assert resultado["noticias"] == "análise de notícias"
    assert resultado["erros"] == {"Analyzer": None}
    assert resultado["tentativas"] == {"Analyzer": 0}
