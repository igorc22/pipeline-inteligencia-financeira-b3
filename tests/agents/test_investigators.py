from fluxo_financeiro.agents.investigators import investigator_agent


def test_investigator_agent_existe():
    """Test que o investigator_agent foi inicializado corretamente."""
    assert investigator_agent is not None


def test_investigator_agent_tem_tools():
    """Test que o agente tem as 3 tools esperadas."""
    tool_node = investigator_agent.nodes.get('tools')
    assert tool_node is not None, "Nó 'tools' não encontrado — agent pode estar mal configurado"

    # Extract tools from the PregelNode structure
    tool_names = set(tool_node.node.steps[0].tools_by_name.keys())
    assert 'buscar_historico_trimestral' in tool_names
    assert 'buscar_fatos_relevantes' in tool_names
    assert 'buscar_noticias_web' in tool_names
    assert len(tool_names) == 3
