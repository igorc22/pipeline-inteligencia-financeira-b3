from typing import Literal
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from fluxo_financeiro.shared.config import MODEL
from fluxo_financeiro.shared.types import MessagesState, RouteDecision
from fluxo_financeiro.shared.utils import logger

llm = ChatAnthropic(model=MODEL, temperature=0)


def supervisor_node(state: MessagesState):
    current_loops = state.get("loop_count", 0)
    logger.info(f"[supervisor] inicio — loop_count={current_loops}")
    if current_loops >= 6:
        logger.warning(f"[supervisor] hard stop — loop_count={current_loops} >= 6")
        return {"next_agent": "FINISH", "loop_count": 1}

    # Guard determinístico: se YFinance coletou mas Analyzer ainda não rodou, vai para Analyzer
    agent_names = {m.name for m in state.get("messages", []) if hasattr(m, "name") and m.name}
    if "YFinance" in agent_names and "Analyzer" not in agent_names:
        logger.info("[supervisor] guard: YFinance coletou → forcando Analyzer (passo 1: noticias da empresa)")
        primeira_tarefa = "Busque notícias recentes sobre a empresa no histórico. Use os dados financeiros do YFinance como contexto para identificar o ticker e o nome da empresa."
        return {
            "next_agent": "Analyzer",
            "loop_count": 1,
            "supervisor_reasoning": "YFinance coletou os dados — passando obrigatoriamente para Analyzer (etapa 1: notícias da empresa).",
            "messages": [HumanMessage(content=primeira_tarefa, name="Supervisor")],
        }

    system_prompt = """Você é um coordenador de pesquisa financeira. Você orquestra agentes em múltiplas passagens, cada uma com uma tarefa específica.

    COMO LER O HISTÓRICO:
    - Mensagens com name='YFinance': dados financeiros coletados (preço, histórico, métricas)
    - Mensagens com name='Analyzer': pesquisas já realizadas pelo analista
    - Mensagens com name='Supervisor': tarefas que você mesmo já atribuiu em turnos anteriores

    PIPELINE DE PESQUISA — siga esta ordem rigorosamente:
    Etapa 1 — Dados financeiros: Se não há mensagem do YFinance → rotear para 'YFinance'.
    Etapa 2 — Notícias da empresa: Se há YFinance mas nenhuma mensagem do Analyzer → rotear para 'Analyzer' (já tratado automaticamente pelo guard).
    Etapa 3 — Contexto do setor: Se há exatamente 1 mensagem do Analyzer E nenhuma mensagem do Supervisor menciona "setor" → rotear para 'Analyzer' com task_for_agent focado no setor da empresa identificada nos dados.
    Etapa 4 — Conclusão: Se já há 2 ou mais mensagens do Analyzer → rotear para 'FINISH'.

    COMO CONTAR MENSAGENS DO ANALYZER:
    Conte quantas mensagens têm name='Analyzer' no histórico. Se for 1, a etapa 3 (contexto setorial) ainda não foi feita.

    COMO FORMULAR task_for_agent NA ETAPA 3:
    - Identifique o setor da empresa pelo ticker (ex: VALE3 → mineração/commodities, WEGE3 → automação industrial, PETR4 → petróleo e gás, ITUB4 → bancário)
    - Formule: 'Busque informações sobre o setor de [SETOR] e o posicionamento da [EMPRESA] ([TICKER]) nesse setor. Foque em tendências, concorrentes principais e fatores macroeconômicos relevantes.'

    PREVENÇÃO DE LOOP (CRÍTICO):
    - Se o Analyzer não consegue dados após 2 tentativas, escolha 'FINISH'.
    - Nunca volte para YFinance se ele já reportou que não encontrou dados.
    - Se loop_count >= 5, sempre escolha 'FINISH'."""

    messages_to_evaluate = [SystemMessage(content=system_prompt)] + state["messages"]

    supervisor_chain = llm.with_structured_output(RouteDecision)
    decision = supervisor_chain.invoke(messages_to_evaluate)

    logger.info(f"[supervisor] decisao={decision.next_agent} | tarefa={decision.task_for_agent!r}")

    result = {
        "next_agent": decision.next_agent,
        "loop_count": 1,
        "supervisor_reasoning": decision.reasoning,
    }
    if decision.task_for_agent and decision.next_agent != "FINISH":
        result["messages"] = [HumanMessage(content=decision.task_for_agent, name="Supervisor")]
    return result


def router(state: MessagesState) -> Literal["YFinance", "Analyzer", "__end__"]:
    next_step = state.get("next_agent", "YFinance")
    destino = "__end__" if next_step == "FINISH" else next_step
    logger.debug(f"[router] {next_step} → {destino}")
    if next_step == "FINISH":
        return "__end__"
    return next_step
