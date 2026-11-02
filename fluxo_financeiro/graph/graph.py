from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph import StateGraph, START, END

from fluxo_financeiro.shared.types import MessagesState
from fluxo_financeiro.agents.collectors import yfinance_agent
from fluxo_financeiro.agents.analysts import analyzer_agent
from fluxo_financeiro.agents.investigators import investigator_agent
from fluxo_financeiro.agents.consolidator import consolidar, formatar_relatorio, relatorio_de_emergencia
from fluxo_financeiro.graph.supervisor import supervisor_node, router
from fluxo_financeiro.shared.utils import extrair_ticker, logger
# Exceção à regra de camadas (graph ← agents): o detector é cálculo em código, sem agente,
# então o grafo o chama direto da camada tools. A dependência continua num sentido só.
from fluxo_financeiro.tools.anomalias import detectar_sinais_anomalia


def _ticker_da_conversa(state: MessagesState):
    """Ticker do pedido original do usuário (a primeira mensagem sem `name`)."""
    for m in state["messages"]:
        if isinstance(m, HumanMessage) and not m.name:
            return extrair_ticker(m.text)
    return None


def yfinance_node(state: MessagesState):
    logger.info(f"[node] YFinance: invocando agente ({len(state['messages'])} msgs)")
    response = yfinance_agent.invoke({"messages": state["messages"]})
    last_message = response["messages"][-1]
    logger.info(f"[node] YFinance: resposta recebida ({len(last_message.text)} chars)")

    # Sinais calculados em código, sem LLM: alimentam o guard do Investigator no Supervisor e
    # entram no texto da mensagem para o Analyzer e o dashboard também verem.
    ticker = _ticker_da_conversa(state)
    sinais = detectar_sinais_anomalia(ticker) if ticker else []
    conteudo = last_message.text
    if sinais:
        conteudo += "\n\nSINAIS DE ANOMALIA (calculados em código):\n" + "\n".join(f"- {s.descricao}" for s in sinais)

    return {
        "messages": [HumanMessage(content=conteudo, name="YFinance")],
        "sinais_anomalia": sinais,
    }


def analyzer_node(state: MessagesState):
    logger.info(f"[node] Analyzer: invocando agente ({len(state['messages'])} msgs)")
    response = analyzer_agent.invoke({"messages": state["messages"]})
    last_message = response["messages"][-1]
    logger.info(f"[node] Analyzer: resposta recebida ({len(last_message.text)} chars)")
    return {"messages": [HumanMessage(content=last_message.text, name="Analyzer")]}


def investigator_node(state: MessagesState):
    logger.info(f"[node] Investigator: invocando agente ({len(state['messages'])} msgs)")
    response = investigator_agent.invoke({"messages": state["messages"]})
    last_message = response["messages"][-1]
    logger.info(f"[node] Investigator: resposta recebida ({len(last_message.text)} chars)")
    return {"messages": [HumanMessage(content=last_message.text, name="Investigator")]}


def consolidador_node(state: MessagesState):
    """Fim de todo fluxo: junta as respostas dos agentes num relatório. Não soma loop_count."""
    logger.info(f"[node] Consolidador: consolidando ({len(state['messages'])} msgs)")
    try:
        relatorio = consolidar(state["messages"])
        conteudo = formatar_relatorio(relatorio, _ticker_da_conversa(state))
    except Exception:
        # A análise já custou várias chamadas: se o último passo falha, entrega o que os agentes disseram.
        logger.exception("[node] Consolidador: falha no LLM, usando as respostas dos agentes")
        relatorio = None
        conteudo = relatorio_de_emergencia(state["messages"])
    logger.info(f"[node] Consolidador: relatório pronto ({len(conteudo)} chars)")
    return {"messages": [HumanMessage(content=conteudo, name="Consolidador")], "relatorio": relatorio}


workflow = StateGraph(MessagesState)

workflow.add_node("Supervisor", supervisor_node)
workflow.add_node("YFinance", yfinance_node)
workflow.add_node("Analyzer", analyzer_node)
workflow.add_node("Investigator", investigator_node)
workflow.add_node("Consolidador", consolidador_node)

workflow.add_edge(START, "Supervisor")
workflow.add_conditional_edges("Supervisor", router)

workflow.add_edge("YFinance", "Supervisor")
workflow.add_edge("Analyzer", "Supervisor")
workflow.add_edge("Investigator", "Supervisor")
workflow.add_edge("Consolidador", END)

app = workflow.compile()
