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


def test_main_recusa_formato_invalido_sem_rodar_o_grafo(_ticker_existe, capsys):
    """Confere que um texto fora do formato da B3 sai com 2 e a mensagem padrão, sem Brapi e sem grafo."""
    existe, _ = _ticker_existe
    with patch.object(e2e, "app") as app_falso:
        assert e2e.main(["XXXX"]) == 2
        app_falso.stream.assert_not_called()
    assert "Ticker inválido: use o código da B3, ex: VALE3." in capsys.readouterr().out
    existe.assert_not_called()


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


def test_conferir_diagnostico_ignora_espacos_nas_pontas():
    """Confere que o strip() do formatar_relatorio não vira falha."""
    assert e2e.conferir_diagnostico(DIAG + "\n\n", f"## Diagnóstico\n{DIAG}\n") == []


def test_conferir_diagnostico_resumido_falha():
    """Confere que um relatório com as quatro palavras, mas sem o texto do Investigator, falha."""
    falhas = e2e.conferir_diagnostico(DIAG, "Causa, Natureza, Evidências e Impacto resumidos.")
    assert falhas == ["o relatório final não traz o diagnóstico do Investigator na íntegra"]


def test_conferir_diagnostico_sem_secao():
    """Confere que diagnóstico sem uma seção ainda é acusado."""
    diag = DIAG.replace("- Impacto: baixo", "")
    assert "diagnóstico sem as seções: Impacto" in e2e.conferir_diagnostico(diag, diag)


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
