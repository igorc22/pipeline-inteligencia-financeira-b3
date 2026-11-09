from unittest.mock import patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.types import Send

from fluxo_financeiro.agents.analysts import SECAO_NOTICIAS, SECAO_SETOR
from fluxo_financeiro.graph.supervisor import (
    PARALELO,
    SUPERVISOR_PROMPT,
    TAREFA_ANALISTA,
    _houve_paralelo,
    _tarefa_investigador,
    historico_do_ramo,
    supervisor_node,
    router,
)
from fluxo_financeiro.shared.prompts import REGRA_CONTEUDO_EXTERNO
from fluxo_financeiro.shared.retry import MAX_TENTATIVAS
from fluxo_financeiro.shared.types import ErroAgente, MessagesState, RouteDecision, SinalAnomalia


def _state(messages, loop_count=0, next_agent="YFinance", **campos) -> MessagesState:
    return {
        "messages": messages,
        "next_agent": next_agent,
        "loop_count": loop_count,
        "supervisor_reasoning": "",
        **campos,
    }


HISTORICO_ETAPA_4 = [
    HumanMessage(content="Analise VALE3"),
    HumanMessage(content="Lucro líquido caiu 62% no trimestre...", name="YFinance"),
    HumanMessage(content="Busque notícias recentes e o setor...", name="Supervisor"),
    HumanMessage(content=f"{SECAO_NOTICIAS}\nnoticias da empresa...\n{SECAO_SETOR}\ncontexto setorial...",
                 name="Analyzer"),
]

# Campos que os nós gravam no state, no ponto correspondente do histórico acima. O Analyzer grava
# noticias e contexto_setor numa passagem só; CAMPOS_SEM_SETOR é a resposta sem a seção do setor.
CAMPOS_ETAPA_2 = {"dados_mercado": "Lucro líquido caiu 62% no trimestre..."}
CAMPOS_SEM_SETOR = {**CAMPOS_ETAPA_2, "noticias": "noticias da empresa..."}
CAMPOS_ETAPA_4 = {**CAMPOS_SEM_SETOR, "contexto_setor": "contexto setorial..."}


@pytest.fixture
def mock_llm():
    """LLM do supervisor mockado: nenhum teste deste arquivo pode chamar a API real."""
    with patch("fluxo_financeiro.graph.supervisor.llm") as llm:
        yield llm


def _llm_decide(mock_llm, decision: RouteDecision):
    mock_llm.with_structured_output.return_value.invoke.return_value = decision


# ---------------------------------------------------------------------------
# Hard stop e guards (decididos em código, sem LLM)
# ---------------------------------------------------------------------------

def test_supervisor_node_hard_stop(mock_llm):
    """Confere que o supervisor encerra em loop_count >= 6 sem consultar o LLM."""
    result = supervisor_node(_state([HumanMessage(content="test")], loop_count=6))
    assert result["decidido_por"] == "hard_stop"
    assert result["next_agent"] == "FINISH"
    mock_llm.with_structured_output.assert_not_called()


def test_supervisor_guard_yfinance_para_analyzer(mock_llm):
    """Confere que, com dados coletados e sem Analyzer, o guard força o Analyzer com a tarefa única (empresa e setor)."""
    messages = [
        HumanMessage(content="Analise WEGE3"),
        HumanMessage(content="dados...", name="YFinance"),
    ]
    state = _state(messages, loop_count=1, dados_mercado="dados...")

    result = supervisor_node(state)
    assert result["decidido_por"] == "guard"

    assert result["next_agent"] == "Analyzer"
    assert len(result["messages"]) == 1
    assert result["messages"][0].name == "Supervisor"
    assert result["messages"][0].content == TAREFA_ANALISTA(messages)
    mock_llm.with_structured_output.assert_not_called()


def test_tarefa_do_analista_pede_empresa_e_setor():
    """Confere que a tarefa única pede as notícias da empresa e o setor, com o ticker e os títulos das duas seções."""
    tarefa = TAREFA_ANALISTA([HumanMessage("Analise VALE3"), HumanMessage("dados...", name="YFinance")])

    assert "notícias recentes sobre a empresa" in tarefa
    assert "setor" in tarefa and "VALE3" in tarefa
    assert "setor e subsetor (ou a indústria)" in tarefa
    assert "Se os dados trazem os maiores do setor, compare a empresa com eles." in tarefa
    assert tarefa.index(SECAO_NOTICIAS) < tarefa.index(SECAO_SETOR)


def test_supervisor_guard_investigator_retorna_finish(mock_llm):
    """Confere que, com o diagnóstico do Investigator no state, o supervisor retorna FINISH sem LLM."""
    state = _state(
        HISTORICO_ETAPA_4 + [HumanMessage(content="causa identificada...", name="Investigator")],
        loop_count=4,
        next_agent="Investigator",
        **CAMPOS_ETAPA_4,
        diagnostico="causa identificada...",
    )
    result = supervisor_node(state)
    assert result["decidido_por"] == "guard"
    assert result["next_agent"] == "FINISH"
    mock_llm.with_structured_output.assert_not_called()


QUEDA = SinalAnomalia(tipo="queda_lucro", descricao="Lucro de VALE3.SA caiu 35% contra o ano anterior.")


def test_etapa_2_com_sinais_vai_para_o_paralelo(mock_llm):
    """Confere que, na Etapa 2 com sinais de anomalia, o guard despacha o paralelo com duas tarefas do Supervisor e sem consultar o LLM."""
    messages = [
        HumanMessage(content="Analise VALE3"),
        HumanMessage(content="dados de mercado...", name="YFinance"),
    ]
    state = _state(messages, loop_count=1, dados_mercado="dados de mercado...", sinais_anomalia=[QUEDA])

    result = supervisor_node(state)
    assert result["decidido_por"] == "guard"
    assert result["next_agent"] == "Analyzer+Investigator"
    assert result["loop_count"] == 1
    assert len(result["messages"]) == 2
    assert result["messages"][0].name == "Supervisor"
    assert result["messages"][0].content == TAREFA_ANALISTA(messages)
    assert result["messages"][1].name == "Supervisor"
    assert QUEDA.descricao in result["messages"][1].content
    assert "queda_lucro" in result["supervisor_reasoning"]
    mock_llm.with_structured_output.assert_not_called()


def test_sem_contexto_setor_nao_reenvia_o_analista(mock_llm):
    """Confere que o Analyzer que respondeu sem a seção do setor não volta: com o Investigator resolvido, o guard vai ao FINISH."""
    state = _state(HISTORICO_ETAPA_4, loop_count=2, **CAMPOS_SEM_SETOR, diagnostico="causa...")

    result = supervisor_node(state)

    assert result["decidido_por"] == "guard"
    assert result["next_agent"] == "FINISH"
    mock_llm.with_structured_output.assert_not_called()


def test_sem_contexto_setor_e_sem_sinais_vai_ao_llm(mock_llm):
    """Confere que, sem a seção do setor e sem sinais, nenhum guard reenvia o Analyzer: quem decide é o LLM (Etapa 4)."""
    _llm_decide(mock_llm, RouteDecision(reasoning="sem anomalia", next_agent="FINISH"))
    state = _state(HISTORICO_ETAPA_4, loop_count=2, **CAMPOS_SEM_SETOR)

    result = supervisor_node(state)

    assert result["decidido_por"] == "llm"
    assert result["next_agent"] == "FINISH"
    mock_llm.with_structured_output.return_value.invoke.assert_called_once()


# ---------------------------------------------------------------------------
# Guards lendo os campos do state, não as mensagens
# ---------------------------------------------------------------------------

def test_guard_le_campos_e_nao_mensagens(mock_llm):
    """Confere que o guard lê os campos do state e não conta mensagens: com dados_mercado e sinais, vai para o paralelo mesmo com uma só mensagem no histórico."""
    state = _state([HumanMessage(content="Analise VALE3")], loop_count=1, **CAMPOS_ETAPA_2, sinais_anomalia=[QUEDA])

    result = supervisor_node(state)
    assert result["decidido_por"] == "guard"
    assert result["next_agent"] == "Analyzer+Investigator"
    mock_llm.with_structured_output.assert_not_called()


def test_investigator_finish_pelo_campo(mock_llm):
    """Confere que o diagnostico no state basta para o FINISH, mesmo sem mensagem do Investigator."""
    state = _state(HISTORICO_ETAPA_4, loop_count=4, next_agent="Investigator",
                   **CAMPOS_ETAPA_4, diagnostico="- Causa identificada: impairment")

    result = supervisor_node(state)
    assert result["decidido_por"] == "guard"
    assert result["next_agent"] == "FINISH"
    mock_llm.with_structured_output.assert_not_called()


def test_estado_inicial_sem_campos_vai_ao_llm(mock_llm):
    """Confere que o estado inicial, sem loop_count nem campos de agente, chega ao LLM sem KeyError."""
    _llm_decide(mock_llm, RouteDecision(reasoning="sem dados ainda", next_agent="YFinance",
                                        task_for_agent="Colete os dados de VALE3."))

    result = supervisor_node({"messages": [HumanMessage("Analise VALE3")]})
    assert result["decidido_por"] == "llm"
    assert result["next_agent"] == "YFinance"
    mock_llm.with_structured_output.return_value.invoke.assert_called_once()


def test_mensagem_duplicada_nao_engana_o_guard(mock_llm):
    """Confere que mensagens duplicadas ou de erro do Analyzer sem o campo noticias gravado não impedem o guard de disparar o paralelo."""
    erro = HumanMessage(content="Erro: Analyzer falhou...", name="Analyzer")
    state = _state(HISTORICO_ETAPA_4 + [erro], loop_count=3, **CAMPOS_ETAPA_2)  # 2 mensagens, nenhum campo
    state["sinais_anomalia"] = [QUEDA]

    result = supervisor_node(state)
    assert result["decidido_por"] == "guard"
    assert result["next_agent"] == "Analyzer+Investigator"
    assert len(result["messages"]) == 2
    assert result["messages"][0].content == TAREFA_ANALISTA(state["messages"])
    mock_llm.with_structured_output.assert_not_called()


def test_campo_vazio_conta_como_preenchido(mock_llm):
    """Confere que campos gravados vazios (agente sem resposta) contam como resolvidos para o guard avançar para FINISH."""
    result = supervisor_node(_state([HumanMessage(content="Analise VALE3")], loop_count=2,
                                    **CAMPOS_ETAPA_2, noticias="", diagnostico=""))
    assert result["next_agent"] == "FINISH"
    assert result["decidido_por"] == "guard"
    mock_llm.with_structured_output.assert_not_called()


# ---------------------------------------------------------------------------
# Guard de erro: o nó já repetiu localmente; o coordenador reenvia uma vez ou segue sem o agente
# ---------------------------------------------------------------------------

def _erro(tipo="transitorio", tentativas=1):
    return ErroAgente(tipo=tipo, mensagem="TimeoutError: lento", tentativas=tentativas)


def test_reenvia_agente_com_erro_temporario(mock_llm):
    """Confere que um erro temporário abaixo do limite reenvia o mesmo agente, sem contar volta e sem LLM."""
    state = _state([HumanMessage(content="Analise VALE3")], loop_count=4, **CAMPOS_ETAPA_4,
                   sinais_anomalia=[QUEDA],
                   erros={"Investigator": _erro()}, tentativas={"Investigator": 1})

    result = supervisor_node(state)

    assert result["next_agent"] == "Investigator"
    assert result["decidido_por"] == "guard"
    assert result["loop_count"] == 0
    assert "messages" not in result  # o agente relê a última tarefa do histórico
    assert result["supervisor_reasoning"] == (
        f"Investigator falhou com erro temporário: nova tentativa (2 de {MAX_TENTATIVAS})."
    )
    mock_llm.with_structured_output.assert_not_called()


def test_nao_reenvia_erro_permanente(mock_llm):
    """Confere que um erro permanente não é reenviado: com Investigator já concluído, o guard avança para FINISH."""
    state = _state([HumanMessage(content="Analise VALE3")], loop_count=2, **CAMPOS_ETAPA_2,
                   diagnostico="causa...",
                   erros={"Analyzer": _erro("permanente")}, tentativas={"Analyzer": 1})

    result = supervisor_node(state)

    assert result["next_agent"] == "FINISH"
    assert result["decidido_por"] == "guard"
    assert result["loop_count"] == 1
    mock_llm.with_structured_output.assert_not_called()


def test_nao_reenvia_depois_do_limite(mock_llm):
    """Confere que, com o limite atingido, o agente não é reenviado e a decisão segue a etapa seguinte."""
    _llm_decide(mock_llm, RouteDecision(reasoning="sem anomalia", next_agent="FINISH"))
    state = _state([HumanMessage(content="Analise VALE3")], loop_count=3, **CAMPOS_ETAPA_2,
                   erros={"Analyzer": _erro(tentativas=MAX_TENTATIVAS)},
                   tentativas={"Analyzer": MAX_TENTATIVAS})

    result = supervisor_node(state)

    assert result["next_agent"] == "FINISH"
    assert result["decidido_por"] == "llm"
    assert result["loop_count"] == 1


def test_analyzer_desistiu_segue_para_o_investigator(mock_llm):
    """Confere que o Analyzer que desistiu não volta: com o Investigator já concluído, o guard avança para FINISH."""
    state = _state([HumanMessage(content="Analise VALE3")], loop_count=3, **CAMPOS_ETAPA_2,
                   diagnostico="causa...",
                   erros={"Analyzer": _erro(tentativas=2)}, tentativas={"Analyzer": 2})

    result = supervisor_node(state)

    assert result["next_agent"] == "FINISH"
    assert result["decidido_por"] == "guard"
    mock_llm.with_structured_output.assert_not_called()


def test_yfinance_desistiu_vai_para_finish(mock_llm):
    """Confere que, sem os dados de mercado depois do limite, o fluxo encerra (o Consolidador anota a falta)."""
    state = _state([HumanMessage(content="Analise VALE3")], loop_count=1,
                   erros={"YFinance": _erro("permanente")}, tentativas={"YFinance": 1})

    result = supervisor_node(state)

    assert result["next_agent"] == "FINISH"
    assert result["decidido_por"] == "guard"
    mock_llm.with_structured_output.assert_not_called()


def test_investigator_desistiu_vai_para_finish(mock_llm):
    """Confere que o Investigator que desistiu encerra o fluxo como se tivesse concluído."""
    state = _state([HumanMessage(content="Analise VALE3")], loop_count=5, **CAMPOS_ETAPA_4,
                   sinais_anomalia=[QUEDA],
                   erros={"Investigator": _erro(tentativas=2)}, tentativas={"Investigator": 2})

    result = supervisor_node(state)

    assert result["next_agent"] == "FINISH"
    assert result["decidido_por"] == "guard"
    mock_llm.with_structured_output.assert_not_called()


def test_llm_nao_reenvia_agente_que_desistiu(mock_llm):
    """Confere que, se o LLM escolhe o Analyzer que desistiu nas notícias (1 mensagem dele, a do erro), o fluxo vai ao FINISH."""
    _llm_decide(mock_llm, RouteDecision(reasoning="falta o setor", next_agent="Analyzer",
                                        task_for_agent="Busque informações sobre o setor da WEGE3"))
    state = _state(
        [HumanMessage(content="Analise WEGE3"),
         HumanMessage(content="dados da WEGE3", name="YFinance"),
         HumanMessage(content="Busque notícias recentes...", name="Supervisor"),
         HumanMessage(content="Erro: Analyzer falhou depois de 1 tentativa (permanente): ValueError: chave", name="Analyzer")],
        loop_count=2, dados_mercado="dados da WEGE3",
        erros={"Analyzer": _erro("permanente")}, tentativas={"Analyzer": 1},
    )

    result = supervisor_node(state)

    mock_llm.with_structured_output.return_value.invoke.assert_called_once()
    assert result["next_agent"] == "FINISH"
    assert result["decidido_por"] == "guard"
    assert result["loop_count"] == 1
    assert "messages" not in result
    assert "Analyzer" in result["supervisor_reasoning"]


def test_erro_limpo_nao_reenvia(mock_llm):
    """Confere que um erro já limpo ({agente: None}) não dispara o reenvio: o guard de etapa decide."""
    state = _state([HumanMessage(content="Analise VALE3")], loop_count=1, **CAMPOS_ETAPA_2,
                   erros={"YFinance": None}, tentativas={"YFinance": 0})

    result = supervisor_node(state)

    assert result["next_agent"] == "Analyzer"
    assert result["loop_count"] == 1  # o reenvio não conta volta; o guard de etapa conta
    assert result["messages"][0].content == TAREFA_ANALISTA(state["messages"])
    mock_llm.with_structured_output.assert_not_called()


# ---------------------------------------------------------------------------
# Decisões do LLM (Etapa 4)
# ---------------------------------------------------------------------------

def test_supervisor_etapa4_roteia_investigator_com_tarefa(mock_llm):
    """Confere que, quando o LLM detecta anomalia, a task_for_agent entra no histórico como Supervisor."""
    tarefa = "Investigue a seguinte anomalia identificada na análise de VALE3: queda de 62% no lucro."
    _llm_decide(mock_llm, RouteDecision(
        reasoning="Queda de lucro sem explicação nas notícias.",
        next_agent="Investigator",
        task_for_agent=tarefa,
    ))

    result = supervisor_node(_state(HISTORICO_ETAPA_4, loop_count=3, **CAMPOS_ETAPA_4))
    assert result["decidido_por"] == "llm"

    assert result["next_agent"] == "Investigator"
    assert result["supervisor_reasoning"] == "Queda de lucro sem explicação nas notícias."
    assert result["messages"][0].name == "Supervisor"
    assert result["messages"][0].content == tarefa
    assert result["loop_count"] == 1


def test_supervisor_etapa4_sem_anomalia_finaliza_sem_mensagem(mock_llm):
    """Confere que FINISH não injeta mensagem do Supervisor no histórico, mesmo se o LLM mandar tarefa."""
    _llm_decide(mock_llm, RouteDecision(
        reasoning="Dados consistentes com as notícias.",
        next_agent="FINISH",
        task_for_agent="(ignorado)",
    ))

    result = supervisor_node(_state(HISTORICO_ETAPA_4, loop_count=3, **CAMPOS_ETAPA_4))
    assert result["decidido_por"] == "llm"

    assert result["next_agent"] == "FINISH"
    assert "messages" not in result


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("next_agent, destino", [
    ("YFinance", "YFinance"),
    ("Analyzer", "Analyzer"),
    ("Investigator", "Investigator"),
    ("FINISH", "Consolidador"),
])
def test_router(next_agent, destino):
    """Confere que o router mapeia cada decisão para o nó correto (FINISH → Consolidador, que vai ao END)."""
    assert router(_state([HumanMessage(content="test")], next_agent=next_agent)) == destino


def test_router_paralelo_devolve_dois_sends():
    """Confere que o router converte a decisão PARALELO em dois objetos Send (Analyzer e Investigator), isolando o histórico de cada ramo."""
    tarefa_ana = HumanMessage(content=TAREFA_ANALISTA([HumanMessage("Analise VALE3"), HumanMessage("dados...", name="YFinance")]), name="Supervisor")
    tarefa_inv = HumanMessage(content=_tarefa_investigador([QUEDA]), name="Supervisor")
    messages = [
        HumanMessage(content="Analise VALE3"),
        HumanMessage(content="dados...", name="YFinance"),
        tarefa_ana,
        tarefa_inv,
    ]
    state = _state(messages, next_agent=PARALELO, sinais_anomalia=[QUEDA])

    sends = router(state)
    assert isinstance(sends, list)
    assert len(sends) == 2
    assert all(isinstance(s, Send) for s in sends)
    assert sends[0].node == "Analyzer"
    assert sends[1].node == "Investigator"

    msgs_ana = sends[0].arg["messages"]
    assert msgs_ana[-1].content == tarefa_ana.content
    assert not any(m.content == tarefa_inv.content for m in msgs_ana)

    msgs_inv = sends[1].arg["messages"]
    assert msgs_inv[-1].content == tarefa_inv.content
    assert not any(m.content == tarefa_ana.content for m in msgs_inv)


def test_historico_do_ramo_com_mensagens_nao_humanas_mantem_isolamento():
    """Confere que o historico_do_ramo preserva o isolamento entre tarefas mesmo quando SystemMessage ou mensagens de outros tipos precedem o pedido do usuário."""
    sys_msg = SystemMessage(content="Você é um assistente financeiro especializado na B3.")
    tool_msg = ToolMessage(content="metadados de inicialização", tool_call_id="call_init")
    empty_user = HumanMessage(content="")
    pedido = HumanMessage(content="Analise VALE3")
    yfinance = HumanMessage(content="dados...", name="YFinance")

    messages = [sys_msg, tool_msg, empty_user, pedido, yfinance]
    tarefa_ana = HumanMessage(content=TAREFA_ANALISTA(messages), name="Supervisor")
    tarefa_inv = HumanMessage(content=_tarefa_investigador([QUEDA]), name="Supervisor")

    state = _state(
        messages + [tarefa_ana, tarefa_inv],
        next_agent=PARALELO,
        sinais_anomalia=[QUEDA],
    )

    # 1. TAREFA_ANALISTA deve extrair VALE3 com sucesso, ignorando mensagens que não contêm o ticker
    assert "VALE3" in tarefa_ana.content

    # 2. historico_do_ramo para Investigator deve filtrar tarefa_ana e preservar tarefa_inv
    msgs_inv = historico_do_ramo(state, "Investigator")
    assert msgs_inv[-1].content == tarefa_inv.content
    assert not any(m.content == tarefa_ana.content for m in msgs_inv)
    assert any(m.content == tarefa_inv.content for m in msgs_inv)

    # 3. historico_do_ramo para Analyzer deve filtrar tarefa_inv e preservar tarefa_ana
    msgs_ana = historico_do_ramo(state, "Analyzer")
    assert msgs_ana[-1].content == tarefa_ana.content
    assert not any(m.content == tarefa_inv.content for m in msgs_ana)
    assert any(m.content == tarefa_ana.content for m in msgs_ana)

    # 4. _houve_paralelo deve retornar True mesmo com mensagens não-humanas e SystemMessage
    assert _houve_paralelo(state) is True


@pytest.mark.parametrize("valor_corrompido", [
    None,
    "",
    "AGENTE_DESCONHECIDO",
    123,
    [],
])
def test_router_trata_next_agent_corrompido_com_fallback_para_consolidador(valor_corrompido):
    """Confere que o router trata com segurança valores corrompidos ou inesperados de next_agent, redirecionando para o Consolidador."""
    state = _state([HumanMessage(content="test")], next_agent=valor_corrompido)
    assert router(state) == "Consolidador"


# ---------------------------------------------------------------------------
# Prompt em XML (D47)
# ---------------------------------------------------------------------------

def test_supervisor_prompt_mantem_contratos():
    """Confere que a reescrita em XML manteve o que o pipeline e os guards dependem."""
    for trecho in ("SINAIS DE ANOMALIA", "YFinance", "Analyzer", "Investigator", "FINISH",
                   "Um investidor ficaria com dúvida de POR QUE"):
        assert trecho in SUPERVISOR_PROMPT
    assert REGRA_CONTEUDO_EXTERNO in SUPERVISOR_PROMPT
    assert "<pipeline>" in SUPERVISOR_PROMPT and "</pipeline>" in SUPERVISOR_PROMPT


def test_supervisor_prompt_tem_o_analista_numa_passagem():
    """Confere que o prompt não manda mais o Analyzer duas vezes e que a Etapa 4 vem depois da resposta do Analyzer."""
    assert "exatamente 1 mensagem do Analyzer" not in SUPERVISOR_PROMPT
    assert "2 ou mais mensagens do Analyzer" not in SUPERVISOR_PROMPT
    assert "depois da resposta do Analyzer" in SUPERVISOR_PROMPT
    assert SECAO_SETOR in SUPERVISOR_PROMPT


def test_supervisor_prompt_sem_indentacao_herdada():
    """Confere que nenhuma linha do prompt carrega a indentação de 4 espaços do código antigo."""
    assert not any(linha.startswith("    -") for linha in SUPERVISOR_PROMPT.splitlines())


def test_supervisor_envia_o_prompt_como_system_message(mock_llm):
    """Confere que a etapa 4 sem sinais manda exatamente o SUPERVISOR_PROMPT como primeira mensagem."""
    _llm_decide(mock_llm, RouteDecision(reasoning="ok", next_agent="FINISH"))

    supervisor_node(_state(HISTORICO_ETAPA_4, loop_count=3, **CAMPOS_ETAPA_4))

    mensagens = mock_llm.with_structured_output.return_value.invoke.call_args.args[0]
    assert mensagens[0].content == SUPERVISOR_PROMPT
