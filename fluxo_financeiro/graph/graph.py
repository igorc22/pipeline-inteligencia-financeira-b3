from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph import StateGraph, START, END

from fluxo_financeiro.shared.types import MessagesState
from fluxo_financeiro.agents.collectors import yfinance_agent
from fluxo_financeiro.agents.analysts import analyzer_agent
from fluxo_financeiro.agents.investigators import investigator_agent
from fluxo_financeiro.graph.supervisor import supervisor_node, router
from fluxo_financeiro.shared.utils import logger


def yfinance_node(state: MessagesState):
    logger.info(f"[node] YFinance: invocando agente ({len(state['messages'])} msgs)")
    response = yfinance_agent.invoke({"messages": state["messages"]})
    last_message = response["messages"][-1]
    logger.info(f"[node] YFinance: resposta recebida ({len(last_message.content)} chars)")
    return {"messages": [HumanMessage(content=last_message.content, name="YFinance")]}


def analyzer_node(state: MessagesState):
    logger.info(f"[node] Analyzer: invocando agente ({len(state['messages'])} msgs)")
    response = analyzer_agent.invoke({"messages": state["messages"]})
    last_message = response["messages"][-1]
    logger.info(f"[node] Analyzer: resposta recebida ({len(last_message.content)} chars)")
    return {"messages": [HumanMessage(content=last_message.content, name="Analyzer")]}


def investigator_node(state: MessagesState):
    logger.info(f"[node] Investigator: invocando agente ({len(state['messages'])} msgs)")
    response = investigator_agent.invoke({"messages": state["messages"]})
    last_message = response["messages"][-1]
    logger.info(f"[node] Investigator: resposta recebida ({len(last_message.content)} chars)")
    return {"messages": [HumanMessage(content=last_message.content, name="Investigator")]}


workflow = StateGraph(MessagesState)

workflow.add_node("Supervisor", supervisor_node)
workflow.add_node("YFinance", yfinance_node)
workflow.add_node("Analyzer", analyzer_node)
workflow.add_node("Investigator", investigator_node)

workflow.add_edge(START, "Supervisor")
workflow.add_conditional_edges("Supervisor", router)

workflow.add_edge("YFinance", "Supervisor")
workflow.add_edge("Analyzer", "Supervisor")
workflow.add_edge("Investigator", "Supervisor")

app = workflow.compile()
