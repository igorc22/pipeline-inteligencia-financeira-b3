import json

from langchain_core.messages import HumanMessage

from dashboard.visao import (
    _conteudo,
    _texto_dot,
    agrupar_achados_por_rodada,
    decisao_do_fim,
    dividir_indicadores,
    dot_do_caminho,
    dot_do_caminho_em_progresso,
    dot_do_subgrafo_pesquisa,
    escapar_markdown,
    limpar_tags_externas,
    montar_passos,
    parou_no_hard_stop,
    passo_do_consolidador,
    raciocinio_do_fim,
    resumo_em_progresso,
    resumo_pesquisa,
    rotulo_agente_em_execucao,
    rotulo_em_execucao,
    separar_indicador,
    state_para_json,
    status_execucao,
)
from fluxo_financeiro.shared.types import ErroAgente, PesquisaFeita, RelatorioFinal, SinalAnomalia


def _sup(decidido_por, proximo, tarefa=None, raciocinio=None, loop_count=1):
    """Evento do Supervisor no formato do stream_mode="updates"."""
    update = {"next_agent": proximo, "loop_count": loop_count, "decidido_por": decidido_por}
    if raciocinio:
        update["supervisor_reasoning"] = raciocinio
    if tarefa:
        update["messages"] = [HumanMessage(tarefa, name="Supervisor")]
    return ("Supervisor", update)


def _worker(nome, texto):
    return (nome, {"messages": [HumanMessage(texto, name=nome)]})


FLUXO_NORMAL = [
    _sup("llm", "YFinance", "Colete", "Histórico vazio."),
    _worker("YFinance", "Preço Atual: R$ 52.71"),
    _sup("guard", "Analyzer", "Busque notícias e setor", "YFinance coletou."),
    _worker("Analyzer", "## Notícias da empresa\nNotícias.\n\n## Contexto do setor\nSetor."),
    _sup("llm", "FINISH", None, "Sem anomalia."),
    ("Consolidador", {"messages": [HumanMessage("# Relatório", name="Consolidador")]}),
]


def test_separar_indicador():
    """Confere que separa no primeiro ': ' e devolve None quando não há valor."""
    assert separar_indicador("P/L: 5.0x") == ("P/L", "5.0x")
    assert separar_indicador("Abertura: 10:30") == ("Abertura", "10:30")
    assert separar_indicador("Lucro subiu") == ("Lucro subiu", None)


def test_montar_passos_fluxo_normal():
    """Confere que cada worker vira um passo com a tarefa e a decisão do Supervisor anterior (Analyzer em passagem única)."""
    passos = montar_passos(FLUXO_NORMAL)

    assert [p.rotulo for p in passos] == ["YFinance", "Analyzer"]
    assert [p.decidido_por for p in passos] == ["llm", "guard"]
    assert passos[1].entrada == "Busque notícias e setor"
    assert passos[1].raciocinio == "YFinance coletou."
    assert "## Contexto do setor" in passos[1].saida
    assert [p.numero for p in passos] == [1, 2]
    assert decisao_do_fim(FLUXO_NORMAL) == "llm"
    assert parou_no_hard_stop(FLUXO_NORMAL) is False


def test_montar_passos_hard_stop():
    """Confere que a 3ª passagem do Analyzer ganha número e que o hard stop é detectado."""
    eventos = [
        _sup("llm", "YFinance", "Colete"),
        _worker("YFinance", "dados"),
        _sup("guard", "Analyzer", "notícias"),
        _worker("Analyzer", "a1"),
        _sup("guard", "Analyzer", "setor"),
        _worker("Analyzer", "a2"),
        _sup("llm", "Analyzer", "mais"),
        _worker("Analyzer", "a3"),
        _sup("hard_stop", "FINISH"),
    ]

    passos = montar_passos(eventos)

    assert [p.rotulo for p in passos] == ["YFinance", "Analyzer", "Analyzer (2)", "Analyzer (3)"]
    assert decisao_do_fim(eventos) == "hard_stop"
    assert parou_no_hard_stop(eventos) is True


def test_montar_passos_sem_supervisor_antes():
    """Confere que um worker sem Supervisor antes fica sem entrada, decisão e raciocínio."""
    passos = montar_passos([_worker("YFinance", "dados")])

    assert passos[0].entrada is None
    assert passos[0].decidido_por is None
    assert passos[0].raciocinio is None


def _arestas(dot, origem, destino):
    """Setas que apontam de origem para destino (a volta é desenhada como destino -> origem com dir=back)."""
    linhas = [linha.strip() for linha in dot.splitlines() if "style=invis" not in linha]  # só posicionam
    diretas = [l for l in linhas if l.startswith(f"{origem} -> {destino} ") and "dir=back" not in l]
    reversas = [l for l in linhas if l.startswith(f"{destino} -> {origem} ") and "dir=back" in l]
    return diretas + reversas


def test_dot_do_caminho_supervisor_no_centro():
    """Confere que o Supervisor é o centro: cada ida sai dele, numerada e com quem decidiu; a volta é tracejada."""
    dot = dot_do_caminho(montar_passos(FLUXO_NORMAL), decisao_do_fim(FLUXO_NORMAL))

    assert len(_arestas(dot, "inicio", "supervisor")) == 1
    assert 'label="1 · LLM"' in _arestas(dot, "supervisor", "yfinance")[0]
    idas_analyzer = _arestas(dot, "supervisor", "analyzer")
    assert len(idas_analyzer) == 1
    assert 'label="2 · guard"' in idas_analyzer[0]
    assert 'label="3 · LLM"' in _arestas(dot, "supervisor", "consolidador")[0]
    assert "dashed" in _arestas(dot, "yfinance", "supervisor")[0]
    assert len(_arestas(dot, "analyzer", "supervisor")) == 1
    assert len(_arestas(dot, "consolidador", "fim")) == 1


def test_dot_do_caminho_investigator_apagado_so_quando_nao_rodou():
    """Confere que o Investigator aparece apagado, sem seta, quando não rodou; quando roda, ganha a seta numerada."""
    sem = dot_do_caminho(montar_passos(FLUXO_NORMAL), "llm")
    assert "não rodou" in sem
    assert not _arestas(sem, "supervisor", "investigator")

    com_investigator = FLUXO_NORMAL[:4] + [
        _sup("llm", "Investigator", "Investigue"),
        _worker("Investigator", "Causa: impairment"),
        _sup("guard", "FINISH"),
    ]
    com = dot_do_caminho(montar_passos(com_investigator), "guard")
    assert "não rodou" not in com
    assert 'label="3 · LLM"' in _arestas(com, "supervisor", "investigator")[0]
    assert 'label="4 · guard"' in _arestas(com, "supervisor", "consolidador")[0]


def test_dot_do_caminho_hard_stop_na_seta_final():
    """Confere que o FINISH do hard stop aparece na seta para o Consolidador."""
    dot = dot_do_caminho(montar_passos(FLUXO_NORMAL), "hard_stop")

    assert 'label="3 · hard stop"' in _arestas(dot, "supervisor", "consolidador")[0]


def test_state_para_json():
    """Confere que o state vira um dict serializável, com mensagens, relatório e sinais."""
    relatorio = RelatorioFinal(resumo="Lucro caiu.", indicadores=["P/L: 5.0x"], contexto="",
                               riscos=[], limitacoes=[])
    state = {
        "messages": [HumanMessage("Analise PETR4"), HumanMessage("dados", name="YFinance")],
        "loop_count": 4,
        "relatorio": relatorio,
        "sinais_anomalia": [SinalAnomalia(tipo="prejuizo", descricao="Prejuízo no trimestre.")],
    }

    resultado = state_para_json(state)

    json.dumps(resultado)  # não pode levantar
    assert resultado["messages"][1] == {"tipo": "HumanMessage", "name": "YFinance", "conteudo": "dados"}
    assert resultado["relatorio"]["resumo"] == "Lucro caiu."
    assert resultado["sinais_anomalia"][0]["tipo"] == "prejuizo"
    assert resultado["loop_count"] == 4


def test_state_para_json_converte_erros_dentro_do_dicionario():
    """Confere que os ErroAgente dentro de `erros` viram dict e que o erro limpo (None) continua None."""
    state = {
        "erros": {"Analyzer": ErroAgente(tipo="transitorio", mensagem="TimeoutError: lento", tentativas=2),
                  "YFinance": None},
        "tentativas": {"Analyzer": 2, "YFinance": 0},
    }

    resultado = state_para_json(state)

    json.dumps(resultado)  # sem default: não pode levantar
    assert resultado["erros"]["Analyzer"] == {"tipo": "transitorio", "mensagem": "TimeoutError: lento", "tentativas": 2}
    assert resultado["erros"]["YFinance"] is None
    assert resultado["tentativas"] == {"Analyzer": 2, "YFinance": 0}


def test_escapar_markdown_protege_cifrao():
    """Confere que o $ dos valores em reais não vira fórmula no markdown do Streamlit."""
    assert escapar_markdown("R$ 3,2 bi contra R$ 5,0 bi") == "R\\$ 3,2 bi contra R\\$ 5,0 bi"
    assert escapar_markdown("sem cifrão") == "sem cifrão"


def test_dot_do_caminho_interrompido_nao_desenha_consolidador():
    """Confere que, quando a análise falhou antes do fim, nada chega ao Consolidador e aparece 'Interrompido'."""
    passos = montar_passos(FLUXO_NORMAL[:2])  # só o YFinance rodou

    dot = dot_do_caminho(passos, None, consolidou=False)

    assert "Interrompido" in dot
    assert _arestas(dot, "yfinance", "interrompido")
    assert not _arestas(dot, "supervisor", "consolidador")
    assert not _arestas(dot, "consolidador", "fim")


def test_dividir_indicadores_manda_texto_longo_para_lista():
    """Confere que só valores curtos viram quadro; longos e sem ': ' viram linha de texto inteira."""
    longo = "Lucro líquido: R$ 3,2 bi (queda de 45% contra o 2T25)"
    quadros, linhas = dividir_indicadores(["P/L: 5.0x", longo, "Lucro em alta"])

    assert quadros == [("P/L", "5.0x")]
    assert linhas == [longo, "Lucro em alta"]


def test_dot_do_caminho_raciocinio_vira_tooltip_da_seta():
    """Confere que o raciocínio do Supervisor aparece ao passar o mouse na seta (aspas escapadas no DOT)."""
    eventos = [_sup("llm", "YFinance", "Colete", 'Sem dados da "PETR4".'), _worker("YFinance", "dados")]

    dot = dot_do_caminho(montar_passos(eventos), None)

    assert 'tooltip="Sem dados da \\"PETR4\\"."' in _arestas(dot, "supervisor", "yfinance")[0]


def test_passo_do_consolidador():
    """Confere que o Consolidador vira o último passo, com a decisão de encerrar e o relatório como saída."""
    passo = passo_do_consolidador(FLUXO_NORMAL, numero=3)

    assert passo.agente == "Consolidador"
    assert passo.numero == 3
    assert passo.decidido_por == "llm"
    assert passo.raciocinio == "Sem anomalia."
    assert passo.saida == "# Relatório"
    assert passo_do_consolidador(FLUXO_NORMAL[:2], numero=2) is None  # não chegou ao fim


def test_rotulo_agente_em_execucao():
    """Confere que o rótulo do agente em execução identifica YFinance, Analyzer (passagem única e extras), Investigator e Consolidador."""
    assert rotulo_agente_em_execucao("YFinance", 0) == "YFinance"
    assert rotulo_agente_em_execucao("Analyzer", 0) == "Analyzer"
    assert rotulo_agente_em_execucao("Analyzer", 1) == "Analyzer (2)"
    assert rotulo_agente_em_execucao("Analyzer", 2) == "Analyzer (3)"
    assert rotulo_agente_em_execucao("Investigator", 0) == "Investigator"
    assert rotulo_agente_em_execucao("FINISH", 0) == "Consolidador"


def test_status_execucao():
    """Confere que o texto de status em execução formata ticker e rótulo do agente."""
    assert status_execucao("PETR4", "YFinance") == "Analisando PETR4: YFinance..."
    assert status_execucao("VALE3", "Analyzer") == "Analisando VALE3: Analyzer..."
    assert status_execucao("WEGE3", "Consolidador") == "Analisando WEGE3: Consolidador..."


def test_dot_do_caminho_em_progresso_destaca_no_ativo_e_seta_em_voo():
    """Confere que o DOT em progresso destaca o nó que está rodando agora e a seta ativa com maior espessura e negrito."""
    eventos = [_sup("llm", "YFinance", "Colete dados", "Histórico vazio.")]
    dot = dot_do_caminho_em_progresso(eventos)

    assert 'yfinance [label="YFinance\\n(rodando agora)"' in dot
    assert 'penwidth=3' in dot
    assert 'fillcolor="#fff8e1"' in dot
    assert 'style="rounded,filled,bold"' in dot
    assert 'analyzer [label="Analyzer\\n(não rodou)"' in dot
    assert 'investigator [label="Investigator\\n(não rodou)"' in dot
    assert 'consolidador [label="Consolidador\\n(não rodou)"' in dot

    setas_yfinance = _arestas(dot, "supervisor", "yfinance")
    assert len(setas_yfinance) == 1
    assert 'label="1 · LLM"' in setas_yfinance[0]
    assert 'penwidth=2.5' in setas_yfinance[0]
    assert 'style="bold"' in setas_yfinance[0]
    assert 'tooltip="Histórico vazio."' in setas_yfinance[0]

    # Nó ainda em execução não possui volta tracejada
    voltas = [a for a in _arestas(dot, "yfinance", "supervisor") if "dashed" in a]
    assert not voltas
    assert "fim" not in dot
    assert "interrompido" not in dot


def test_dot_do_caminho_em_progresso_segunda_passagem_analyzer():
    """Confere que a segunda passagem do Analyzer mantém o retorno da primeira e ativa a nova seta e nó."""
    eventos = [
        _sup("llm", "YFinance", "Colete"),
        _worker("YFinance", "dados coletados"),
        _sup("guard", "Analyzer", "notícias"),
        _worker("Analyzer", "notícias coletadas"),
        _sup("guard", "Analyzer", "setor", "Falta o setor."),
    ]
    dot = dot_do_caminho_em_progresso(eventos)

    # YFinance completado
    assert 'yfinance [label="YFinance", color="#e0a030"' in dot
    # Analyzer rodando agora
    assert 'analyzer [label="Analyzer\\n(rodando agora)"' in dot

    # Seta 1 para YFinance (já concluída, sem negrito extra)
    seta_yf = _arestas(dot, "supervisor", "yfinance")[0]
    assert 'label="1 · LLM"' in seta_yf
    assert 'penwidth=2.5' not in seta_yf

    # Duas setas para o Analyzer: a 2ª (já concluída) e a 3ª (ativa)
    setas_analyzer = _arestas(dot, "supervisor", "analyzer")
    assert len(setas_analyzer) == 2
    assert 'label="2 · guard"' in setas_analyzer[0]
    assert 'penwidth=2.5' not in setas_analyzer[0]

    assert 'label="3 · guard"' in setas_analyzer[1]
    assert 'penwidth=2.5' in setas_analyzer[1]
    assert 'style="bold"' in setas_analyzer[1]
    assert 'tooltip="Falta o setor."' in setas_analyzer[1]

    # Retorno da 1ª passagem do Analyzer já existe
    assert len(_arestas(dot, "analyzer", "supervisor")) == 1


def test_dot_do_caminho_em_progresso_finish_ativa_consolidador():
    """Confere que o evento de FINISH ativa o Consolidador como nó em execução e realça a seta para ele."""
    eventos = FLUXO_NORMAL[:4] + [_sup("llm", "FINISH", None, "Sem anomalia.")]
    dot = dot_do_caminho_em_progresso(eventos)

    assert 'consolidador [label="Consolidador\\n(rodando agora)"' in dot
    assert 'penwidth=3' in dot

    setas_consolidador = _arestas(dot, "supervisor", "consolidador")
    assert len(setas_consolidador) == 1
    assert 'label="3 · LLM"' in setas_consolidador[0]
    assert 'penwidth=2.5' in setas_consolidador[0]
    assert 'style="bold"' in setas_consolidador[0]
    assert 'tooltip="Sem anomalia."' in setas_consolidador[0]
    assert "fim" not in dot


def test_dot_do_caminho_em_progresso_investigator():
    """Confere que o encaminhamento ao Investigator destaca seu nó e a respectiva seta ativa."""
    eventos = FLUXO_NORMAL[:4] + [_sup("llm", "Investigator", "Investigue", "P/L anômalo.")]
    dot = dot_do_caminho_em_progresso(eventos)

    assert 'investigator [label="Investigator\\n(rodando agora)"' in dot
    setas_inv = _arestas(dot, "supervisor", "investigator")
    assert len(setas_inv) == 1
    assert 'label="3 · LLM"' in setas_inv[0]
    assert 'penwidth=2.5' in setas_inv[0]
    assert 'style="bold"' in setas_inv[0]
    assert 'tooltip="P/L anômalo."' in setas_inv[0]


def test_dot_do_caminho_em_progresso_pos_conclusao_consolidador():
    """Confere que, após a conclusão do Consolidador, o grafo final é renderizado com nó Fim."""
    dot = dot_do_caminho_em_progresso(FLUXO_NORMAL)

    assert "Fim" in dot
    assert "(rodando agora)" not in dot
    assert len(_arestas(dot, "consolidador", "fim")) == 1


def test_rotulo_e_status_execucao_com_valores_vazios_ou_nulos():
    """Confere que valores vazios ou nulos de proximo não quebram o rótulo nem injetam 'None' no status."""
    assert rotulo_agente_em_execucao(None) == ""
    assert rotulo_agente_em_execucao("") == ""
    assert status_execucao("PETR4", None) == "Analisando PETR4..."
    assert status_execucao("PETR4", "") == "Analisando PETR4..."


def test_dot_do_caminho_em_progresso_eventos_vazios():
    """Confere que eventos vazios geram o diagrama inicial sem nenhum nó ativo e sem nós finais."""
    dot = dot_do_caminho_em_progresso([])
    assert "supervisor" in dot
    assert "(rodando agora)" not in dot
    assert "Fim" not in dot
    assert "Interrompido" not in dot
    assert 'yfinance [label="YFinance\\n(não rodou)"' in dot
    assert 'consolidador [label="Consolidador\\n(não rodou)"' in dot


def test_dot_do_caminho_em_progresso_quarta_passagem_analyzer():
    """Confere que a quarta passagem do Analyzer gera rótulo numérico e destaca o nó e a 4ª seta."""
    eventos = [
        _sup("llm", "YFinance", "Colete"),
        _worker("YFinance", "dados"),
        _sup("guard", "Analyzer", "passo 1"),
        _worker("Analyzer", "notícias 1"),
        _sup("guard", "Analyzer", "passo 2"),
        _worker("Analyzer", "notícias 2"),
        _sup("guard", "Analyzer", "passo 3"),
        _worker("Analyzer", "notícias 3"),
        _sup("guard", "Analyzer", "passo 4", "Busca adicional."),
    ]
    assert rotulo_agente_em_execucao("Analyzer", 3) == "Analyzer (4)"
    dot = dot_do_caminho_em_progresso(eventos)
    assert 'analyzer [label="Analyzer\\n(rodando agora)"' in dot
    setas_analyzer = _arestas(dot, "supervisor", "analyzer")
    assert len(setas_analyzer) == 4
    assert 'label="5 · guard"' in setas_analyzer[3]
    assert 'penwidth=2.5' in setas_analyzer[3]
    assert 'tooltip="Busca adicional."' in setas_analyzer[3]


def test_dot_do_caminho_consolidador_preserva_tooltip_raciocinio():
    """Confere que a seta do Supervisor para o Consolidador após a conclusão preserva o tooltip com o raciocínio."""
    dot = dot_do_caminho_em_progresso(FLUXO_NORMAL)
    setas = _arestas(dot, "supervisor", "consolidador")
    assert len(setas) == 1
    assert 'tooltip="Sem anomalia."' in setas[0]


def test_conteudo_com_tipos_diversos_e_nulos():
    """Confere que _conteudo lida com strings, dicionários, None e mensagens sem quebrar."""
    assert _conteudo(None) == ""
    assert _conteudo("relatório em string") == "relatório em string"
    assert _conteudo({"content": "dados em dict"}) == "dados em dict"
    assert _conteudo({"sem_content": 123}) == "{'sem_content': 123}"
    assert _conteudo(HumanMessage("mensagem langchain")) == "mensagem langchain"


def test_texto_dot_com_valores_nao_string():
    """Confere que _texto_dot aceita valores numéricos ou não-string sem quebrar e escapa aspas e barras."""
    assert _texto_dot(12345) == "12345"
    assert _texto_dot(None) == ""
    assert _texto_dot('Texto com "aspas" e \\ barra') == 'Texto com \\"aspas\\" e \\\\ barra'


def test_dot_do_caminho_em_progresso_com_raciocinio_nao_string():
    """Confere que o diagrama em progresso lida com raciocínio numérico ou estruturado na decisão ativa."""
    eventos = [_sup("llm", "YFinance", "Colete", raciocinio=42)]
    dot = dot_do_caminho_em_progresso(eventos)
    assert 'tooltip="42"' in dot
    assert 'yfinance [label="YFinance\\n(rodando agora)"' in dot


def test_raciocinio_do_fim():
    """Confere que raciocinio_do_fim extrai o raciocínio da decisão FINISH e tolera payloads nulos ou não-dicionário."""
    eventos = [
        ("Supervisor", "não-dicionário"),
        _sup("llm", "FINISH", None, "Raciocínio de conclusão."),
    ]
    assert raciocinio_do_fim(eventos) == "Raciocínio de conclusão."
    assert raciocinio_do_fim([]) is None
    assert raciocinio_do_fim([("Supervisor", None)]) is None


def test_passo_do_consolidador_com_payload_nao_dicionario():
    """Confere que passo_do_consolidador lida com payloads em string, lista ou nulos sem levantar exceção."""
    assert passo_do_consolidador([("Consolidador", None)], 4) is None
    assert passo_do_consolidador([("Consolidador", {})], 4) is None

    passo = passo_do_consolidador([
        _sup("llm", "FINISH", None, "Concluir"),
        ("Consolidador", "Relatório simples em string"),
    ], 4)
    assert passo is not None
    assert passo.saida == "Relatório simples em string"
    assert passo.raciocinio == "Concluir"


def test_montar_passos_com_payloads_nao_dicionario():
    """Confere que montar_passos aceita updates de workers e supervisor como strings ou None sem quebrar."""
    eventos = [
        ("Supervisor", "decisão inválida"),
        _sup("llm", "YFinance", "Colete"),
        ("YFinance", "dados de mercado em texto"),
    ]
    passos = montar_passos(eventos)
    assert len(passos) == 1
    assert passos[0].agente == "YFinance"
    assert passos[0].saida == "dados de mercado em texto"


def test_separar_indicador_e_escapar_markdown_com_nao_strings():
    """Confere que separar_indicador e escapar_markdown aceitam valores não-string ou nulos com segurança."""
    assert separar_indicador(None) == ("", None)
    assert separar_indicador(12345) == ("12345", None)
    assert escapar_markdown(None) == ""
    assert escapar_markdown(100) == "100"


def test_state_para_json_com_tipos_nao_dicionario():
    """Confere que state_para_json lida com state não-dicionário ou messages não-lista sem quebrar."""
    assert state_para_json(None) == {}
    assert state_para_json("invalido") == {}
    assert state_para_json({"messages": "mensagem única"}) == {"messages": "mensagem única"}


def test_montar_passos_paralelo_atribui_tarefas_e_decisao_corretas():
    """Confere que o passo paralelo gera passos com mesmo número, tarefas isoladas e decisão preservada."""
    eventos = [
        _sup("llm", "YFinance", "Colete dados da VALE3"),
        _worker("YFinance", "P/L: 5.2x"),
        ("Supervisor", {
            "next_agent": "Analyzer+Investigator",
            "loop_count": 1,
            "decidido_por": "guard",
            "supervisor_reasoning": "Sinais de anomalia encontrados.",
            "messages": [
                HumanMessage("## Notícias da empresa: Busque notícias da VALE3", name="Supervisor"),
                HumanMessage("Investigue a anomalia na queda de lucro", name="Supervisor"),
            ],
        }),
        _worker("Analyzer", "Notícias e setor da VALE3"),
        _worker("Investigator", "Diagnóstico: impairment"),
        _sup("guard", "FINISH", None, "Concluir"),
        ("Consolidador", {"messages": [HumanMessage("# Relatório Final", name="Consolidador")]}),
    ]

    passos = montar_passos(eventos)

    assert len(passos) == 3
    assert [p.numero for p in passos] == [1, 2, 2]
    assert [p.agente for p in passos] == ["YFinance", "Analyzer", "Investigator"]

    assert passos[1].entrada == "## Notícias da empresa: Busque notícias da VALE3"
    assert passos[1].decidido_por == "guard"
    assert passos[1].raciocinio == "Sinais de anomalia encontrados."

    assert passos[2].entrada == "Investigue a anomalia na queda de lucro"
    assert passos[2].decidido_por == "guard"
    assert passos[2].raciocinio == "Sinais de anomalia encontrados."

    num_consolidador = max(p.numero for p in passos) + 1
    final = passo_do_consolidador(eventos, numero=num_consolidador)
    assert final is not None
    assert final.numero == 3
    assert final.decidido_por == "guard"


def test_dot_do_caminho_paralelo_duas_setas_mesmo_passo():
    """Confere que o diagrama final concluído do paralelo tem setas de ida com label 2 para ambos e 3 para o consolidador."""
    eventos = [
        _sup("llm", "YFinance", "Colete"),
        _worker("YFinance", "dados"),
        ("Supervisor", {
            "next_agent": "Analyzer+Investigator",
            "loop_count": 1,
            "decidido_por": "guard",
            "supervisor_reasoning": "Anomalia detectada.",
            "messages": [
                HumanMessage("## Notícias da empresa", name="Supervisor"),
                HumanMessage("Investigue", name="Supervisor"),
            ],
        }),
        _worker("Analyzer", "notícias"),
        _worker("Investigator", "diagnóstico"),
        _sup("guard", "FINISH", None, "Pronto"),
        ("Consolidador", {"messages": [HumanMessage("# Relatório", name="Consolidador")]}),
    ]
    passos = montar_passos(eventos)
    dot = dot_do_caminho(passos, decisao_fim="guard", consolidou=True, raciocinio_fim="Pronto")

    setas_analyzer = _arestas(dot, "supervisor", "analyzer")
    assert any('label="2 · guard"' in s for s in setas_analyzer)

    setas_investigator = _arestas(dot, "supervisor", "investigator")
    assert any('label="2 · guard"' in s for s in setas_investigator)

    setas_consolidador = _arestas(dot, "supervisor", "consolidador")
    assert any('label="3 · guard"' in s for s in setas_consolidador)

    assert "dashed" in _arestas(dot, "analyzer", "supervisor")[0]
    assert "dashed" in _arestas(dot, "investigator", "supervisor")[0]


def test_dot_do_caminho_em_progresso_paralelo_ambos_ativos():
    """Confere que enquanto o passo paralelo inicia, ambos os nós aparecem como rodando agora e com setas ativas."""
    eventos = [
        _sup("llm", "YFinance", "Colete"),
        _worker("YFinance", "dados"),
        ("Supervisor", {
            "next_agent": "Analyzer+Investigator",
            "loop_count": 1,
            "decidido_por": "guard",
            "supervisor_reasoning": "Paralelo iniciado.",
            "messages": [
                HumanMessage("## Notícias da empresa", name="Supervisor"),
                HumanMessage("Investigue", name="Supervisor"),
            ],
        }),
    ]
    dot = dot_do_caminho_em_progresso(eventos)

    assert 'analyzer [label="Analyzer\\n(rodando agora)"' in dot
    assert 'investigator [label="Investigator\\n(rodando agora)"' in dot

    setas_ana = _arestas(dot, "supervisor", "analyzer")
    assert any('label="2 · guard"' in s and 'penwidth=2.5' in s and 'style="bold"' in s for s in setas_ana)

    setas_inv = _arestas(dot, "supervisor", "investigator")
    assert any('label="2 · guard"' in s and 'penwidth=2.5' in s and 'style="bold"' in s for s in setas_inv)


def test_dot_do_caminho_em_progresso_paralelo_um_ramo_concluido():
    """Confere que quando o Analyzer termina mas o Investigator ainda roda, o Investigator permanece destacado."""
    eventos = [
        _sup("llm", "YFinance", "Colete"),
        _worker("YFinance", "dados"),
        ("Supervisor", {
            "next_agent": "Analyzer+Investigator",
            "loop_count": 1,
            "decidido_por": "guard",
            "supervisor_reasoning": "Paralelo iniciado.",
            "messages": [
                HumanMessage("## Notícias da empresa", name="Supervisor"),
                HumanMessage("Investigue", name="Supervisor"),
            ],
        }),
        _worker("Analyzer", "notícias concluídas"),
    ]
    dot = dot_do_caminho_em_progresso(eventos)

    assert 'analyzer [label="Analyzer", color="#3fb37f"' in dot
    assert len(_arestas(dot, "analyzer", "supervisor")) == 1

    assert 'investigator [label="Investigator\\n(rodando agora)"' in dot
    setas_inv = _arestas(dot, "supervisor", "investigator")
    assert any('label="2 · guard"' in s and 'penwidth=2.5' in s and 'style="bold"' in s for s in setas_inv)


def test_resumo_em_progresso_paralelo():
    """Confere que o resumo em progresso exibe rótulo combinado e passo correto durante o paralelo."""
    eventos = [
        _sup("llm", "YFinance", "Colete"),
        _worker("YFinance", "dados"),
        ("Supervisor", {
            "next_agent": "Analyzer+Investigator",
            "loop_count": 1,
            "decidido_por": "guard",
            "supervisor_reasoning": "Anomalias na receita.",
            "messages": [HumanMessage("notícias"), HumanMessage("investigue")],
        }),
    ]
    resumo = resumo_em_progresso(eventos)
    assert "**2 · Analyzer e Investigator** — rodando agora" in resumo
    assert "Anomalias na receita." in resumo


def test_resumo_e_rotulo_em_progresso_paralelo_um_ramo_concluido():
    """Confere que quando um ramo do paralelo termina antes do outro, o ramo restante continua como 'rodando agora'."""
    eventos = [
        _sup("llm", "YFinance", "Colete"),
        _worker("YFinance", "dados"),
        ("Supervisor", {
            "next_agent": "Analyzer+Investigator",
            "loop_count": 1,
            "decidido_por": "guard",
            "supervisor_reasoning": "Queda de lucro detectada.",
            "messages": [
                HumanMessage("## Notícias da empresa", name="Supervisor"),
                HumanMessage("Investigue", name="Supervisor"),
            ],
        }),
        _worker("Investigator", "Diagnóstico pronto primeiro"),
    ]

    assert rotulo_em_execucao(eventos) == "Analyzer"
    resumo = resumo_em_progresso(eventos)
    assert "**2 · Investigator** *(via guard)* — investigou a anomalia" in resumo
    assert "**2 · Analyzer** — rodando agora *(decidido por guard)*" in resumo
    assert "Queda de lucro detectada." in resumo


def test_montar_passos_preserva_tarefa_no_reenvio_do_coordenador():
    """Confere que o reenvio do coordenador (sem nova mensagem de tarefa e com loop_count=0) preserva a tarefa original e marca reenvio."""
    erro_temp = ErroAgente(tipo="transitorio", mensagem="TimeoutError: lento", tentativas=1)
    eventos = [
        _sup("llm", "YFinance", "Colete dados"),
        _worker("YFinance", "dados"),
        ("Supervisor", {
            "next_agent": "Analyzer+Investigator",
            "loop_count": 1,
            "decidido_por": "guard",
            "supervisor_reasoning": "Anomalia encontrada.",
            "messages": [
                HumanMessage("## Notícias da empresa: VALE3", name="Supervisor"),
                HumanMessage("Investigue queda de 53% no lucro da VALE3", name="Supervisor"),
            ],
        }),
        _worker("Analyzer", "## Notícias da empresa\nOk\n\n## Contexto do setor\nOk"),
        ("Investigator", {
            "messages": [HumanMessage("Erro: Investigator falhou depois de 2 tentativas (transitorio): Timeout", name="Investigator")],
            "erros": {"Investigator": erro_temp},
            "tentativas": {"Investigator": 1},
        }),
        _sup("guard", "Investigator", None, "Investigator falhou com erro temporário: nova tentativa (2 de 2).", loop_count=0),
        ("Investigator", {
            "messages": [HumanMessage("- Causa identificada: queda do minério", name="Investigator")],
            "erros": {"Investigator": None},
            "tentativas": {"Investigator": 0},
        }),
        _sup("guard", "FINISH", None, "Concluído"),
        ("Consolidador", {"messages": [HumanMessage("# Relatório", name="Consolidador")]}),
    ]

    passos = montar_passos(eventos)

    assert len(passos) == 4
    passo_falha = passos[2]
    assert passo_falha.agente == "Investigator"
    assert passo_falha.erro is not None
    assert passo_falha.desistiu is False
    assert passo_falha.reenvio is False
    assert passo_falha.entrada == "Investigue queda de 53% no lucro da VALE3"

    passo_reenvio = passos[3]
    assert passo_reenvio.agente == "Investigator"
    assert passo_reenvio.erro is None
    assert passo_reenvio.reenvio is True
    assert passo_reenvio.entrada == "Investigue queda de 53% no lucro da VALE3"

    dot = dot_do_caminho(passos, decisao_fim="guard", consolidou=True)
    setas_inv = _arestas(dot, "supervisor", "investigator")
    assert len(setas_inv) == 2
    assert 'label="2 · guard · falhou"' in setas_inv[0]
    assert 'label="3 · guard (reenvio)"' in setas_inv[1]
    assert "(desistiu)" not in dot


def test_dot_e_resumo_quando_agente_desiste():
    """Confere que um agente que esgota as tentativas ou tem erro permanente aparece como 'desistiu' no grafo e no resumo."""
    erro_final = ErroAgente(tipo="transitorio", mensagem="TimeoutError: lento", tentativas=2)
    eventos = [
        _sup("llm", "YFinance", "Colete dados"),
        _worker("YFinance", "dados"),
        _sup("guard", "Analyzer", "Busque notícias e setor", "Passando para o Analyzer."),
        ("Analyzer", {
            "messages": [HumanMessage("Erro: Analyzer falhou depois de 2 tentativas (transitorio): lento", name="Analyzer")],
            "erros": {"Analyzer": ErroAgente(tipo="transitorio", mensagem="lento", tentativas=1)},
            "tentativas": {"Analyzer": 1},
        }),
        _sup("guard", "Analyzer", None, "Nova tentativa (2 de 2).", loop_count=0),
        ("Analyzer", {
            "messages": [HumanMessage("Erro: Analyzer falhou depois de 2 tentativas (transitorio): lento", name="Analyzer")],
            "erros": {"Analyzer": erro_final},
            "tentativas": {"Analyzer": 2},
        }),
        _sup("llm", "FINISH", None, "Seguir sem Analyzer."),
        ("Consolidador", {"messages": [HumanMessage("# Relatório com limitação", name="Consolidador")]}),
    ]

    passos = montar_passos(eventos)
    assert passos[1].desistiu is False
    assert passos[2].desistiu is True
    assert passos[2].reenvio is True
    assert passos[2].entrada == "Busque notícias e setor"

    dot = dot_do_caminho(passos, decisao_fim="llm", consolidou=True)
    assert 'analyzer [label="Analyzer\\n(desistiu)"' in dot

    resumo = resumo_em_progresso(eventos)
    assert "falhou na 1ª rodada (erro temporário)" in resumo
    assert "falhou (erro temporário); etapa ficou de fora" in resumo


def test_subgrafo_pesquisa_funcoes_puras():
    """Confere o resumo, limpeza de tags, agrupamento por rodada e DOT do subgrafo de pesquisa do Investigator."""
    pesquisa = PesquisaFeita(
        perguntas=[
            "Por que o lucro da VALE3 caiu no 3T26?",
            "Houve impairment na VALE3 no 3T26?",
            "Qual o efeito da provisão da Samarco?",
        ],
        achados=[
            {
                "pergunta": "Por que o lucro da VALE3 caiu no 3T26?",
                "rodada": 1,
                "texto": '<conteudo_externo origem="google_search">\nLucro caiu 53% com recuo do minério.\nFontes: vale.com\n</conteudo_externo>',
            },
            {
                "pergunta": "Houve impairment na VALE3 no 3T26?",
                "rodada": 1,
                "texto": "",
            },
            {
                "pergunta": "Qual o efeito da provisão da Samarco?",
                "rodada": 2,
                "texto": '<conteudo_externo origem="tavily">\nProvisão de US$ 322 milhões.\nFontes: infomoney.com.br\n</conteudo_externo>',
            },
        ],
        voltas=1,
        historico="Métrica  2026-09-30\nNet Income 1.25B",
    )

    assert limpar_tags_externas(pesquisa.achados[0]["texto"]) == "Lucro caiu 53% com recuo do minério.\nFontes: vale.com"
    rodadas = agrupar_achados_por_rodada(pesquisa)
    assert [r for r, _ in rodadas] == [1, 2]
    assert len(rodadas[0][1]) == 2
    assert len(rodadas[1][1]) == 1

    resumo = resumo_pesquisa(pesquisa)
    assert "3 perguntas geradas" in resumo
    assert "2/3 buscas com resultado" in resumo
    assert "1 volta extra pedida pelo crítico" in resumo

    dot = dot_do_subgrafo_pesquisa(pesquisa)
    assert "digraph subgrafo_pesquisa" in dot
    assert 'gerar_perguntas [label="gerar_perguntas\\n(2 perguntas)"' in dot
    assert 'buscar [label="buscar (Send)\\n(2/3 com achados)"' in dot
    assert 'criticar -> buscar [label="1x lacunas (Send)"' in dot


