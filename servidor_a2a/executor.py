import asyncio

from a2a.helpers import new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.utils.errors import UnsupportedOperationError
from langchain_core.messages import HumanMessage
from langsmith.run_helpers import tracing_context

from fluxo_financeiro import app
from fluxo_financeiro.shared.utils import logger
from servidor_a2a.entrada import resolver_entrada
from servidor_a2a.saida import NOME_ARTEFATO, contexto_de_trace, montar_partes, nomes_de_trace

# O Supervisor passa várias vezes e não é uma etapa da análise para quem chama
NOS_SEM_AVISO = {"Supervisor"}


class ExecutorPipeline(AgentExecutor):
    """Liga o protocolo A2A ao grafo: valida o ticker, roda a análise e publica o resultado."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        tarefa = context.current_task or new_task_from_user_message(context.message)
        if not context.current_task:
            await event_queue.enqueue_event(tarefa)
        atualizador = TaskUpdater(event_queue, tarefa.id, tarefa.context_id)

        def mensagem(texto: str):
            return atualizador.new_agent_message([new_text_part(texto)])

        # A conferência na Brapi é uma chamada de rede síncrona: fora do laço de eventos
        entrada = await asyncio.to_thread(resolver_entrada, context.get_user_input())
        if entrada.recusa:
            await atualizador.reject(mensagem(entrada.recusa))
            return

        cabecalhos = context.call_context.state.get("headers", {})
        logger.debug(f"[a2a] cabeçalhos de trace recebidos: {nomes_de_trace(cabecalhos)}")
        pedido = {"messages": [HumanMessage(f"Analise a ação {entrada.ticker}")]}
        estado = None
        logger.info(f"[a2a] {entrada.ticker}: análise iniciada")
        try:
            with tracing_context(**contexto_de_trace(cabecalhos)):
                async for modo, dado in app.astream(pedido, stream_mode=["updates", "values"]):
                    if modo == "values":
                        estado = dado
                        continue
                    for no in dado:
                        if no not in NOS_SEM_AVISO:
                            await atualizador.start_work(mensagem(f"Etapa concluída: {no}"))
            if estado is None:
                raise RuntimeError("o grafo terminou sem estado final")
        except Exception as e:
            # O texto da exceção fica só no log: pode trazer detalhe de chave ou de URL
            logger.exception(f"[a2a] {entrada.ticker}: análise falhou")
            await atualizador.failed(mensagem(f"Erro ao analisar {entrada.ticker}: {type(e).__name__}"))
            return

        await atualizador.add_artifact(montar_partes(entrada.ticker, estado), name=NOME_ARTEFATO)
        await atualizador.complete()
        logger.info(f"[a2a] {entrada.ticker}: análise concluída")

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise UnsupportedOperationError()
