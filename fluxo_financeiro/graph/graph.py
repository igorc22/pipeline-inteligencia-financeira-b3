import re
from typing import Callable

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langgraph.graph import StateGraph, START, END

from fluxo_financeiro.shared.retry import (
    RespostaVazia,
    classificar_erro,
    com_retentativas,
    e_mensagem_de_erro,
    prefixo_de_erro,
)
from fluxo_financeiro.shared.types import ErroAgente, MessagesState
from fluxo_financeiro.agents.collectors import yfinance_agent
from fluxo_financeiro.agents.analysts import analyzer_agent, separar_secoes
from fluxo_financeiro.agents.pesquisa import investigar
from fluxo_financeiro.agents.consolidator import consolidar, formatar_relatorio, relatorio_de_emergencia
from fluxo_financeiro.graph.supervisor import DESTINOS_DO_ROUTER, supervisor_node, router
from fluxo_financeiro.shared.prompts import TAG_CONTEUDO_EXTERNO
from fluxo_financeiro.shared.utils import extrair_ticker, logger
# Exceção à regra de camadas (graph ← agents): o detector é cálculo em código, sem agente,
# então o grafo o chama direto da camada tools. A dependência continua num sentido só.
from fluxo_financeiro.tools.anomalias import detectar_sinais_anomalia
# Mesma exceção: o aviso é a string que a tool escreve quando a Brapi não respondeu, e os
# indicadores do Banco Central entram em código (o LLM do YFinance nem sempre chamaria a tool).
from fluxo_financeiro.tools.financial_data import AVISO_PERFIL_RESERVA, indicadores_economicos_em_texto


def _ticker_da_conversa(state: MessagesState):
    """Ticker do pedido original do usuário (a primeira mensagem sem `name`)."""
    for m in state["messages"]:
        if isinstance(m, HumanMessage) and not m.name:
            return extrair_ticker(m.text)
    return None


# Retry local do nó: o agente inteiro roda até 2 vezes, com 2 s de espera, antes de o erro subir ao
# coordenador. Cada chamada ao LLM já é repetida pela biblioteca do Gemini por baixo disso.
TENTATIVAS_LOCAIS = 2
ESPERA_LOCAL = 2.0
TAMANHO_MENSAGEM_ERRO = 300


def _resumo_do_erro(e: Exception) -> str:
    """Tipo e texto da exceção numa linha, cortado: o erro do Gemini traz o JSON inteiro da resposta."""
    return " ".join(f"{type(e).__name__}: {e}".split())[:TAMANHO_MENSAGEM_ERRO]


def _rodar_com_retry(nome: str, rodar: Callable[[], dict], state: MessagesState) -> dict:
    """Roda o nó repetindo o agente localmente; o que não resolver vira erro estruturado, sem levantar.

    Princípio: cada agente/parte resolve o retry localmente antes de escalar pro coordenador.
    Sucesso: o dict do nó, com o erro e as tentativas do agente zerados (uma nova falha do mesmo
    agente começa com o limite inteiro). Falha final: o erro no state, uma
    mensagem "Erro: ..." com o nome do agente e o campo do agente sem gravar.
    """
    rodadas = 0

    def contando() -> dict:
        nonlocal rodadas
        rodadas += 1
        return rodar()

    try:
        resultado = com_retentativas(
            contando, tentativas=TENTATIVAS_LOCAIS, espera=ESPERA_LOCAL, contexto=f"[node] {nome}"
        )
    except Exception as e:
        tipo = classificar_erro(e)
        falhas = (state.get("tentativas") or {}).get(nome, 0) + 1
        mensagem = _resumo_do_erro(e)
        texto = f"{prefixo_de_erro(nome)}{rodadas} {'tentativa' if rodadas == 1 else 'tentativas'} ({tipo}): {mensagem}"
        logger.error(f"[node] {texto}")
        logger.debug(f"[node] {nome}: traceback da falha", exc_info=True)
        return {
            "messages": [HumanMessage(content=texto, name=nome)],
            "erros": {nome: ErroAgente(tipo=tipo, mensagem=mensagem, tentativas=falhas)},
            "tentativas": {nome: falhas},
        }
    return {**resultado, "erros": {nome: None}, "tentativas": {nome: 0}}


def _historico(nome: str, state: MessagesState) -> list[BaseMessage]:
    """O histórico que o agente recebe, sem os "Erro: ..." dele mesmo.

    Na rodada mandada pelo coordenador, a última mensagem volta a ser a tarefa do Supervisor, como
    na primeira vez, e não o erro da rodada anterior.
    """
    return [m for m in state["messages"] if not e_mensagem_de_erro(m, nome)]


def _saida_das_tools(mensagens_novas) -> str:
    """Texto das tools quando o LLM do YFinance chama as tools e não escreve a resposta final.

    Aconteceu no e2e da VALE3: a mensagem ficou só com os blocos do código, e o relatório saiu sem
    P/L, risco e Piotroski e sem limitação. As tags de conteúdo externo saem (as messages do state
    não levam tags). Sem tool nenhuma, levanta RespostaVazia: o nó repete o agente e, se não
    adiantar, o erro vai para o coordenador.
    """
    saidas = [m.text for m in mensagens_novas if isinstance(m, ToolMessage) and m.text.strip()]
    if not saidas:
        raise RespostaVazia("o agente do YFinance não respondeu e nenhuma tool devolveu dados")
    logger.warning(f"[node] YFinance: resposta final vazia, usando a saída de {len(saidas)} tools")
    texto = "\n\n".join(saidas)
    return re.sub(rf"</?{TAG_CONTEUDO_EXTERNO}[^>]*>\n?", "", texto)


def _texto_final(nome: str, response: dict) -> str:
    """Texto da última mensagem do agente; vazio levanta RespostaVazia (o nó repete o agente)."""
    texto = response["messages"][-1].text
    logger.info(f"[node] {nome}: resposta recebida ({len(texto)} chars)")
    if not texto.strip():
        raise RespostaVazia(f"o agente do {nome} terminou sem resposta final")
    return texto


def _rodar_yfinance(state: MessagesState) -> dict:
    historico = _historico("YFinance", state)
    logger.info(f"[node] YFinance: invocando agente ({len(historico)} msgs)")
    response = yfinance_agent.invoke({"messages": historico})
    conteudo = response["messages"][-1].text
    logger.info(f"[node] YFinance: resposta recebida ({len(conteudo)} chars)")
    mensagens_novas = response["messages"][len(historico):]
    if not conteudo.strip():
        conteudo = _saida_das_tools(mensagens_novas)

    # Depois da resposta do agente: uma RespostaVazia repete o agente sem refazer o detector e o BCB.
    # Sinais calculados em código, sem LLM: alimentam o guard do Investigator no Supervisor e
    # entram no texto da mensagem para o Analyzer e o dashboard também verem.
    ticker = _ticker_da_conversa(state)
    sinais = detectar_sinais_anomalia(ticker) if ticker else []
    # O Consolidador anota a limitação da reserva lendo o aviso na mensagem do YFinance. O prompt
    # manda o agente repassar a linha, mas o LLM pode resumir: o aviso é conferido na saída da tool.
    reserva = any(isinstance(m, ToolMessage) and AVISO_PERFIL_RESERVA in m.text for m in mensagens_novas)
    if reserva and AVISO_PERFIL_RESERVA not in conteudo:
        conteudo += "\n\n" + AVISO_PERFIL_RESERVA
    if sinais:
        conteudo += "\n\nSINAIS DE ANOMALIA (calculados em código):\n" + "\n".join(f"- {s.descricao}" for s in sinais)
    # SELIC, CDI e IPCA de 12 meses: a régua da renda fixa. BCB fora do ar devolve "" e a análise segue sem o bloco.
    bloco_bcb = indicadores_economicos_em_texto()
    if bloco_bcb:
        conteudo += "\n\n" + bloco_bcb

    return {
        "messages": [HumanMessage(content=conteudo, name="YFinance")],
        "sinais_anomalia": sinais,
        "dados_mercado": conteudo,
    }


def yfinance_node(state: MessagesState):
    return _rodar_com_retry("YFinance", lambda: _rodar_yfinance(state), state)


def _rodar_analyzer(state: MessagesState) -> dict:
    historico = _historico("Analyzer", state)
    logger.info(f"[node] Analyzer: invocando agente ({len(historico)} msgs)")
    texto = _texto_final("Analyzer", analyzer_agent.invoke({"messages": historico}))
    # Uma passagem só: notícias da empresa e contexto do setor, em duas seções gravadas cada uma no
    # seu campo. Sem a seção do setor (o LLM ignorou o formato), o texto inteiro vai para noticias e
    # contexto_setor fica None: o Consolidador anota a limitação e o Supervisor não manda o Analyzer
    # de novo. A mensagem do histórico continua sendo a resposta inteira.
    noticias, contexto_setor = separar_secoes(texto)
    return {
        "messages": [HumanMessage(content=texto, name="Analyzer")],
        "noticias": noticias,
        "contexto_setor": contexto_setor,
    }


def analyzer_node(state: MessagesState):
    return _rodar_com_retry("Analyzer", lambda: _rodar_analyzer(state), state)


def _tarefa_do_investigator(state: MessagesState) -> str:
    """A última tarefa do Supervisor no histórico do ramo (sem os erros do próprio Investigator).

    No paralelo, o histórico do ramo só tem a tarefa do Investigator. Sem tarefa nenhuma, o
    subgrafo investiga o próprio pedido do usuário.
    """
    historico = _historico("Investigator", state)
    tarefa = next((m for m in reversed(historico) if isinstance(m, HumanMessage) and m.name == "Supervisor"), None)
    if tarefa is None:
        tarefa = next((m for m in historico if isinstance(m, HumanMessage) and not m.name), None)
    return tarefa.text if tarefa is not None else ""


def _rodar_investigator(state: MessagesState) -> dict:
    # O Investigator é o subgrafo de pesquisa (agents/pesquisa.py): perguntas, buscas em paralelo,
    # síntese e crítico. Uma exceção lá dentro (o LLM fora) sobe até aqui, e o retry do nó roda o
    # subgrafo inteiro de novo.
    tarefa = _tarefa_do_investigator(state)
    ticker = _ticker_da_conversa(state)
    logger.info(f"[node] Investigator: rodando o subgrafo de pesquisa ({ticker})")
    texto, pesquisa = investigar(tarefa, ticker)
    logger.info(f"[node] Investigator: diagnóstico pronto ({len(texto)} chars, {len(pesquisa.achados)} buscas)")
    if not texto.strip():
        raise RespostaVazia("o subgrafo de pesquisa do Investigator terminou sem diagnóstico")
    return {
        "messages": [HumanMessage(content=texto, name="Investigator")],
        "diagnostico": texto,
        "pesquisa": pesquisa,
    }


def investigator_node(state: MessagesState):
    return _rodar_com_retry("Investigator", lambda: _rodar_investigator(state), state)


def consolidador_node(state: MessagesState):
    """Fim de todo fluxo: junta as respostas dos agentes num relatório. Não soma loop_count."""
    logger.info(f"[node] Consolidador: consolidando ({len(state['messages'])} msgs)")
    try:
        relatorio = consolidar(state)
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
# O router devolve um nome ou uma lista de Send (o paralelo): a lista de destinos é explícita para o
# LangGraph desenhar as arestas do Supervisor.
workflow.add_conditional_edges("Supervisor", router, DESTINOS_DO_ROUTER)

workflow.add_edge("YFinance", "Supervisor")
workflow.add_edge("Analyzer", "Supervisor")
workflow.add_edge("Investigator", "Supervisor")
workflow.add_edge("Consolidador", END)

app = workflow.compile()
