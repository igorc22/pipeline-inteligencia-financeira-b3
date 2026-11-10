from fluxo_financeiro.agents.analysts import (
    SECAO_NOTICIAS,
    SECAO_SETOR,
    analyzer_agent,
    separar_secoes,
)


def test_analyzer_agent_tem_tools_de_noticias():
    """Confere que o Analyzer tem Web Search (padrão) e NewsAPI (reserva) registradas."""
    tool_node = analyzer_agent.nodes.get('tools')
    assert tool_node is not None, "Nó 'tools' não encontrado: o agente pode estar mal configurado"
    nomes = set(tool_node.node.steps[0].tools_by_name)
    assert nomes == {'buscar_noticias', 'buscar_noticias_web'}


def test_separar_secoes_com_as_duas():
    """Confere que, com as duas seções, cada uma volta sem o título e sem espaço sobrando."""
    texto = f"{SECAO_NOTICIAS}\nA Vale anunciou X.\n\nE Y.\n\n{SECAO_SETOR}\nMineração em alta.\n"

    assert separar_secoes(texto) == ("A Vale anunciou X.\n\nE Y.", "Mineração em alta.")


def test_separar_secoes_sem_setor():
    """Confere que, sem a seção do setor (o LLM ignorou o formato), o texto inteiro vira notícias e o setor fica None."""
    texto = "A Vale anunciou X. O setor de mineração está em alta."

    assert separar_secoes(texto) == (texto, None)


def test_separar_secoes_titulo_do_setor_no_meio_da_frase_nao_conta():
    """Confere que o título do setor só conta sozinho na linha, não citado dentro de um parágrafo."""
    texto = f"{SECAO_NOTICIAS}\nO relatório tem a parte {SECAO_SETOR} mais adiante."

    assert separar_secoes(texto) == (texto, None)


def test_separar_secoes_setor_vazio_vira_none():
    """Confere que a seção do setor só com o título vira None, para o Consolidador registrar a falta."""
    texto = f"{SECAO_NOTICIAS}\nA Vale anunciou X.\n{SECAO_SETOR}\n  \n"

    assert separar_secoes(texto) == ("A Vale anunciou X.", None)

