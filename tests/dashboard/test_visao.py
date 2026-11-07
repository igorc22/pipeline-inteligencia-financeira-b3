import json

from langchain_core.messages import HumanMessage

from dashboard.visao import (
    decisao_do_fim,
    dividir_indicadores,
    dot_do_caminho,
    escapar_markdown,
    montar_passos,
    parou_no_hard_stop,
    passo_do_consolidador,
    separar_indicador,
    state_para_json,
)
from fluxo_financeiro.shared.types import RelatorioFinal, SinalAnomalia


def _sup(decidido_por, proximo, tarefa=None, raciocinio=None):
    """Evento do Supervisor no formato do stream_mode="updates"."""
    update = {"next_agent": proximo, "loop_count": 1, "decidido_por": decidido_por}
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
    _sup("guard", "Analyzer", "Busque notícias", "YFinance coletou."),
    _worker("Analyzer", "Notícias da empresa"),
    _sup("guard", "Analyzer", "Busque o setor", "Falta o setor."),
    _worker("Analyzer", "Contexto do setor"),
    _sup("llm", "FINISH", None, "Sem anomalia."),
    ("Consolidador", {"messages": [HumanMessage("# Relatório", name="Consolidador")]}),
]


def test_separar_indicador():
    """Confere que separa no primeiro ': ' e devolve None quando não há valor."""
    assert separar_indicador("P/L: 5.0x") == ("P/L", "5.0x")
    assert separar_indicador("Abertura: 10:30") == ("Abertura", "10:30")
    assert separar_indicador("Lucro subiu") == ("Lucro subiu", None)


def test_montar_passos_fluxo_normal():
    """Confere que cada worker vira um passo com a tarefa e a decisão do Supervisor anterior."""
    passos = montar_passos(FLUXO_NORMAL)

    assert [p.rotulo for p in passos] == ["YFinance", "Analyzer (empresa)", "Analyzer (setor)"]
    assert [p.decidido_por for p in passos] == ["llm", "guard", "guard"]
    assert passos[1].entrada == "Busque notícias"
    assert passos[1].raciocinio == "YFinance coletou."
    assert passos[2].saida == "Contexto do setor"
    assert [p.numero for p in passos] == [1, 2, 3]
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

    assert passos[3].rotulo == "Analyzer (3)"
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
    assert len(idas_analyzer) == 2  # empresa e setor
    assert 'label="2 · guard"' in idas_analyzer[0] and 'label="3 · guard"' in idas_analyzer[1]
    assert 'label="4 · LLM"' in _arestas(dot, "supervisor", "consolidador")[0]
    assert "dashed" in _arestas(dot, "yfinance", "supervisor")[0]
    assert len(_arestas(dot, "analyzer", "supervisor")) == 1  # uma volta por agente, não por passagem
    assert len(_arestas(dot, "consolidador", "fim")) == 1


def test_dot_do_caminho_investigator_apagado_so_quando_nao_rodou():
    """Confere que o Investigator aparece apagado, sem seta, quando não rodou; quando roda, ganha a seta numerada."""
    sem = dot_do_caminho(montar_passos(FLUXO_NORMAL), "llm")
    assert "não rodou" in sem
    assert not _arestas(sem, "supervisor", "investigator")

    com_investigator = FLUXO_NORMAL[:6] + [
        _sup("guard", "Investigator", "Investigue"),
        _worker("Investigator", "Causa: impairment"),
        _sup("guard", "FINISH"),
    ]
    com = dot_do_caminho(montar_passos(com_investigator), "guard")
    assert "não rodou" not in com
    assert 'label="4 · guard"' in _arestas(com, "supervisor", "investigator")[0]
    assert 'label="5 · guard"' in _arestas(com, "supervisor", "consolidador")[0]


def test_dot_do_caminho_hard_stop_na_seta_final():
    """Confere que o FINISH do hard stop aparece na seta para o Consolidador."""
    dot = dot_do_caminho(montar_passos(FLUXO_NORMAL), "hard_stop")

    assert 'label="4 · hard stop"' in _arestas(dot, "supervisor", "consolidador")[0]


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
    passo = passo_do_consolidador(FLUXO_NORMAL, numero=4)

    assert passo.agente == "Consolidador"
    assert passo.numero == 4
    assert passo.decidido_por == "llm"
    assert passo.raciocinio == "Sem anomalia."
    assert passo.saida == "# Relatório"
    assert passo_do_consolidador(FLUXO_NORMAL[:2], numero=2) is None  # não chegou ao fim
