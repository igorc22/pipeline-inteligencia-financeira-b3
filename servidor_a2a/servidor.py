import os

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from starlette.applications import Starlette

from servidor_a2a.card import URL_PADRAO, montar_card
from servidor_a2a.executor import ExecutorPipeline


def criar_app() -> Starlette:
    """Aplicação ASGI do agente: o card em /.well-known/agent-card.json e o JSON-RPC em /."""
    card = montar_card(os.getenv("A2A_URL_PUBLICA", URL_PADRAO))
    tratador = DefaultRequestHandler(agent_executor=ExecutorPipeline(), task_store=InMemoryTaskStore(), agent_card=card)
    return Starlette(routes=[
        *create_agent_card_routes(card),
        # O 0.3 no mesmo endereço: clientes antigos e os exemplos do LiteLLM usam message/send
        *create_jsonrpc_routes(tratador, "/", enable_v0_3_compat=True),
    ])


app = criar_app()
