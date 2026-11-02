"""Checagens do scripts/e2e.py que não dependem de chamada real."""
import importlib.util
from pathlib import Path

_CAMINHO = Path(__file__).resolve().parents[2] / "scripts" / "e2e.py"
_spec = importlib.util.spec_from_file_location("e2e", _CAMINHO)
e2e = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(e2e)

DIAG = "- Causa: impairment\n- Natureza: pontual\n- Evidências: 3T26\n- Impacto: baixo"


def test_conferir_diagnostico_ok():
    """Test que diagnóstico completo e copiado na íntegra não gera falha."""
    final = f"# Relatório\n## Diagnóstico da anomalia\n{DIAG}\n## Riscos"
    assert e2e.conferir_diagnostico(DIAG, final) == []


def test_conferir_diagnostico_ignora_espacos_nas_pontas():
    """Test que o strip() do formatar_relatorio não vira falha."""
    assert e2e.conferir_diagnostico(DIAG + "\n\n", f"## Diagnóstico\n{DIAG}\n") == []


def test_conferir_diagnostico_resumido_falha():
    """Test que um relatório com as quatro palavras, mas sem o texto do Investigator, falha."""
    falhas = e2e.conferir_diagnostico(DIAG, "Causa, Natureza, Evidências e Impacto resumidos.")
    assert falhas == ["o relatório final não traz o diagnóstico do Investigator na íntegra"]


def test_conferir_diagnostico_sem_secao():
    """Test que diagnóstico sem uma seção ainda é acusado."""
    diag = DIAG.replace("- Impacto: baixo", "")
    assert "diagnóstico sem as seções: Impacto" in e2e.conferir_diagnostico(diag, diag)
