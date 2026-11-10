from fluxo_financeiro.agents.collectors import yfinance_agent


def test_yfinance_agent_tem_as_tres_tools():
    """Confere que o agente tem exatamente as três tools, com os nomes que o LLM usa no tool-calling."""
    tools = yfinance_agent.nodes["tools"].node.steps[0].tools_by_name
    assert set(tools) == {"buscar_dados_acao_b3", "calcular_metricas_risco", "calcular_piotroski_score"}
