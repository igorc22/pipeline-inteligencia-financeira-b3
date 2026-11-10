"""Checagens do scripts/e2e.py que não dependem de chamada real."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

_CAMINHO = Path(__file__).resolve().parents[2] / "scripts" / "e2e.py"
_spec = importlib.util.spec_from_file_location("e2e", _CAMINHO)
e2e = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(e2e)

DIAG = "- Causa: impairment\n- Natureza: pontual\n- Evidências: 3T26\n- Impacto: baixo"


@pytest.fixture(autouse=True)
def _ticker_existe():
    """A Brapi confere o ticker na entrada: aqui ela é sempre falsa (a rede é bloqueada nos testes)."""
    with patch("fluxo_financeiro.tools.brapi.ticker_existe", return_value=True) as existe, \
         patch("fluxo_financeiro.tools.brapi.sugerir_ticker", return_value=None) as sugere:
        yield existe, sugere


def test_main_recusa_ticker_inexistente_sem_rodar_o_grafo(_ticker_existe, capsys):
    """Confere que o ticker que a Brapi diz não existir sai com 2 e a mensagem nova, sem rodar o grafo."""
    existe, _ = _ticker_existe
    existe.return_value = False
    with patch.object(e2e, "app") as app_falso:
        assert e2e.main(["XXXX3"]) == 2
        app_falso.stream.assert_not_called()
    assert "Ticker não encontrado na B3: XXXX3." in capsys.readouterr().out


def test_conferir_diagnostico_ok():
    """Confere que diagnóstico completo e copiado na íntegra não gera falha."""
    final = f"# Relatório\n## Diagnóstico da anomalia\n{DIAG}\n## Riscos"
    assert e2e.conferir_diagnostico(DIAG, final) == []


def test_conferir_diagnostico_resumido_falha():
    """Confere que um relatório com as quatro palavras, mas sem o texto do Investigator, falha."""
    falhas = e2e.conferir_diagnostico(DIAG, "Causa, Natureza, Evidências e Impacto resumidos.")
    assert falhas == ["o relatório final não traz o diagnóstico do Investigator na íntegra"]


def test_conferir_tags_vazadas():
    """Confere que o e2e aponta os agentes cuja resposta repetiu a tag de conteúdo externo, sem repetir nomes."""
    mensagens = [
        ("YFinance", 'Sumário: <conteudo_externo origem="yfinance">...'),
        ("Analyzer", "notícias ok"),
        ("Analyzer", "setor <conteudo_externo origem=\"google_search\">"),
        ("YFinance", "<conteudo_externo"),
    ]
    assert e2e.conferir_tags_vazadas(mensagens) == ["YFinance", "Analyzer"]
    assert e2e.conferir_tags_vazadas([("Analyzer", "ok")]) == []


def test_rodar_caminho_com_paralelo_e_tempo():
    """Confere que rodar() inclui Supervisor→[Analyzer+Investigator] no caminho e calcula tempo_total."""
    from langchain_core.messages import HumanMessage
    from fluxo_financeiro.shared.types import RelatorioFinal

    eventos = [
        {"Supervisor": {"next_agent": "YFinance", "loop_count": 1}},
        {"YFinance": {"messages": [HumanMessage("dados", name="YFinance")]}},
        {"Supervisor": {"next_agent": "Analyzer+Investigator", "loop_count": 1}},
        {"Analyzer": {"messages": [HumanMessage("noticias", name="Analyzer")]}},
        {"Investigator": {"messages": [HumanMessage(DIAG, name="Investigator")]}},
        {"Supervisor": {"next_agent": "FINISH", "loop_count": 1}},
        {"Consolidador": {
            "messages": [HumanMessage(f"# Relatório\n## Diagnóstico da anomalia\n{DIAG}", name="Consolidador")],
            "relatorio": RelatorioFinal(resumo="ok", indicadores=["P/L: 5.0x"], contexto="ctx", riscos=[], limitacoes=[]),
        }},
    ]
    with patch.object(e2e.app, "stream", return_value=iter(eventos)):
        res = e2e.rodar("VALE3")
    assert "Supervisor→[Analyzer+Investigator]" in res["caminho"]
    assert res["tempo_total"] >= 0.0
    assert "Investigator" in res["mensagens"]


def test_main_espera_investigator_com_paralelo(capsys):
    """Confere que main com --espera-investigator passa quando Investigator ativou no paralelo e exibe o tempo total."""
    from fluxo_financeiro.shared.types import RelatorioFinal

    resultado_falso = {
        "caminho": ["Supervisor→YFinance", "YFinance", "Supervisor→[Analyzer+Investigator]", "Analyzer", "Investigator", "Supervisor→FINISH", "Consolidador"],
        "mensagens": {
            "YFinance": "dados",
            "Analyzer": "noticias",
            "Investigator": DIAG,
            "Consolidador": f"# Relatório\n## Diagnóstico da anomalia\n{DIAG}",
        },
        "todas": [("YFinance", "dados"), ("Analyzer", "noticias"), ("Investigator", DIAG)],
        "relatorio": RelatorioFinal(resumo="ok", indicadores=["P/L: 5.0x"], contexto="ctx", riscos=[], limitacoes=[]),
        "loops": 3,
        "tempo_total": 4.2,
    }
    with patch.object(e2e, "rodar", return_value=resultado_falso):
        codigo = e2e.main(["VALE3", "--espera-investigator"])
    saida = capsys.readouterr().out
    assert codigo == 0
    assert "Tempo total:   4.2 s" in saida
    assert "Investigator:  ATIVADO" in saida


def test_main_espera_investigator_falha_quando_nao_ativa(capsys):
    """Confere que main com --espera-investigator falha com código 1 se o Investigator não ativou."""
    from fluxo_financeiro.shared.types import RelatorioFinal

    resultado_falso = {
        "caminho": ["Supervisor→YFinance", "YFinance", "Supervisor→Analyzer", "Analyzer", "Supervisor→FINISH", "Consolidador"],
        "mensagens": {
            "YFinance": "dados",
            "Analyzer": "noticias",
            "Consolidador": "# Relatório",
        },
        "todas": [("YFinance", "dados"), ("Analyzer", "noticias")],
        "relatorio": RelatorioFinal(resumo="ok", indicadores=["P/L: 5.0x"], contexto="ctx", riscos=[], limitacoes=[]),
        "loops": 3,
        "tempo_total": 2.1,
    }
    with patch.object(e2e, "rodar", return_value=resultado_falso):
        codigo = e2e.main(["WEGE3", "--espera-investigator"])
    saida = capsys.readouterr().out
    assert codigo == 1
    assert "FALHA: esperava o Investigator e ele não foi ativado" in saida
