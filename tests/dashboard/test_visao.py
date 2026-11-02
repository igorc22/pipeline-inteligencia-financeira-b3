import json

from langchain_core.messages import HumanMessage

from dashboard.visao import (
    decisao_do_fim,
    dot_do_caminho,
    montar_passos,
    parou_no_hard_stop,
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
    """Test que separa no primeiro ': ' e devolve None quando não há valor."""
    assert separar_indicador("P/L: 5.0x") == ("P/L", "5.0x")
    assert separar_indicador("Abertura: 10:30") == ("Abertura", "10:30")
    assert separar_indicador("Lucro subiu") == ("Lucro subiu", None)


def test_montar_passos_fluxo_normal():
    """Test que cada worker vira um passo com a tarefa e a decisão do Supervisor anterior."""
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
    """Test que a 3ª passagem do Analyzer ganha número e que o hard stop é detectado."""
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
    """Test que um worker sem Supervisor antes fica sem entrada, decisão e raciocínio."""
    passos = montar_passos([_worker("YFinance", "dados")])

    assert passos[0].entrada is None
    assert passos[0].decidido_por is None
    assert passos[0].raciocinio is None


def test_dot_do_caminho_ordem_e_rotulos():
    """Test que o DOT desenha os passos na ordem, da esquerda para a direita, com quem decidiu."""
    dot = dot_do_caminho(montar_passos(FLUXO_NORMAL), decisao_do_fim(FLUXO_NORMAL))

    assert "rankdir=LR" in dot
    posicoes = [dot.index(r) for r in ["YFinance", "Analyzer (empresa)", "Analyzer (setor)", "Consolidador"]]
    assert posicoes == sorted(posicoes)
    assert 'label="guard"' in dot and 'label="LLM"' in dot


def test_dot_do_caminho_investigator_tracejado():
    """Test que o Investigator aparece tracejado só quando não rodou."""
    sem = dot_do_caminho(montar_passos(FLUXO_NORMAL), "llm")
    assert "não rodou" in sem and "style=dashed" in sem

    com_investigator = FLUXO_NORMAL[:6] + [
        _sup("guard", "Investigator", "Investigue"),
        _worker("Investigator", "Causa: impairment"),
        _sup("guard", "FINISH"),
    ]
    com = dot_do_caminho(montar_passos(com_investigator), "guard")
    assert "não rodou" not in com


def test_state_para_json():
    """Test que o state vira um dict serializável, com mensagens, relatório e sinais."""
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
