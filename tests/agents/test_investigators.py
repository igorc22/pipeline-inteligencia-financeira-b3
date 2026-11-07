from unittest.mock import patch

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from fluxo_financeiro.agents.investigators import (
    MAX_BUSCAS,
    criar_investigator_agent,
    investigator_agent,
)


def test_investigator_agent_tem_tools():
    """Confere que o agente tem as 3 tools esperadas."""
    tool_node = investigator_agent.nodes.get('tools')
    assert tool_node is not None, "Nó 'tools' não encontrado — agent pode estar mal configurado"

    tool_names = set(tool_node.node.steps[0].tools_by_name.keys())
    assert tool_names == {'buscar_historico_trimestral', 'buscar_fatos_relevantes', 'buscar_noticias_web'}


# ---------------------------------------------------------------------------
# Limite de buscas (ToolCallLimitMiddleware)
# ---------------------------------------------------------------------------

class ModeloQueInsisteEmBuscar(BaseChatModel):
    """Modelo falso que pede buscar_fatos_relevantes até receber o aviso de limite; aí conclui."""

    chamadas: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-insistente"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.chamadas += 1
        ultima = messages[-1]
        if isinstance(ultima, ToolMessage) and "limit exceeded" in str(ultima.content):
            resposta = AIMessage(content="- Causa identificada: limite atingido, conclusão parcial")
        elif self.chamadas > 20:  # trava de segurança: o teste falha em vez de rodar para sempre
            resposta = AIMessage(content="sem limite")
        else:
            resposta = AIMessage(content="", tool_calls=[{
                "name": "buscar_fatos_relevantes",
                "args": {"ticker": "VALE3"},
                "id": f"chamada-{self.chamadas}",
            }])
        return ChatResult(generations=[ChatGeneration(message=resposta)])


@patch('fluxo_financeiro.tools.investigation.pesquisar_na_web', return_value="fato relevante")
def test_investigator_para_de_buscar_no_limite(mock_pesquisa):
    """Confere que, mesmo com o modelo insistindo, a busca real roda no máximo MAX_BUSCAS vezes
    e o agente ainda termina com uma conclusão (exit_behavior='continue')."""
    agente = criar_investigator_agent(ModeloQueInsisteEmBuscar())

    resultado = agente.invoke({"messages": [HumanMessage("Investigue a queda de lucro da VALE3")]})

    assert mock_pesquisa.call_count == MAX_BUSCAS
    assert resultado["messages"][-1].content.startswith("- Causa identificada")
