from fluxo_financeiro.agents.analysts import analyzer_agent


def test_analyzer_agent_exists():
    """Test that analyzer_agent is properly initialized."""
    assert analyzer_agent is not None


def test_analyzer_agent_tem_tools_de_noticias():
    """Test que o Analyzer tem NewsAPI (padrão) e Web Search (fallback) registradas."""
    tool_node = analyzer_agent.nodes.get('tools')
    assert tool_node is not None, "Nó 'tools' não encontrado — agent pode estar mal configurado"
    nomes = set(tool_node.node.steps[0].tools_by_name)
    assert nomes == {'buscar_noticias', 'buscar_noticias_web'}
