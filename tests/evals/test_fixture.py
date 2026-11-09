"""Guard offline das fixtures dos evals: roda na suíte padrão (sem o marcador eval), sem rede e sem gastar.

Fixture com formato antigo ou incompleto reprova aqui em milissegundos, antes de qualquer chamada paga
ao juiz. Sem fixture gerada, os testes parametrizados pulam.
"""
import importlib.util
from pathlib import Path

import pytest

from fluxo_financeiro.agents.consolidator import montar_insumos
from tests.evals.helpers import (
    FIXTURES_DIR,
    MAX_CHARS_POR_FONTE,
    MAX_FONTES,
    carregar_fixture,
    contexto_do_agente,
    mensagens,
)

# VERSAO_FIXTURE vem do próprio script que gera a fixture, para os dois lados não divergirem.
_CAMINHO_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "gerar_fixture_eval.py"
_spec = importlib.util.spec_from_file_location("gerar_fixture_eval", _CAMINHO_SCRIPT)
_gerar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gerar)
VERSAO_FIXTURE = _gerar.VERSAO_FIXTURE

FIXTURES = sorted(FIXTURES_DIR.glob("*.json"))
INVESTIGATOR_ESPERADO = {"vale3": True, "wege3": False}
CORTE_CONHECIDO: dict[str, str] = {}  # stem -> onde o corte acontece (Task 6 Step 4); vazio por padrão


def _parametros(marcar_corte=False):
    if not FIXTURES:
        return [pytest.param(None, marks=pytest.mark.skip("nenhuma fixture gerada ainda"), id="sem-fixture")]
    return [
        pytest.param(c, id=c.stem, marks=pytest.mark.xfail(strict=True, reason=CORTE_CONHECIDO[c.stem]))
        if marcar_corte and c.stem in CORTE_CONHECIDO else pytest.param(c, id=c.stem)
        for c in FIXTURES
    ]


@pytest.mark.parametrize("caminho", _parametros())
def test_fixture_tem_o_formato_que_os_evals_leem(caminho):
    """Confere que a versão, as chaves, o relatório, o Consolidador e as passagens seguem o formato esperado."""
    fx = carregar_fixture(caminho)
    assert fx["versao"] == VERSAO_FIXTURE
    assert {"versao", "ticker", "gerado_em", "modelo", "messages", "passagens", "sinais_anomalia", "relatorio"} <= fx.keys()
    assert fx["relatorio"] is not None
    msgs = mensagens(fx)
    assert msgs[-1].name == "Consolidador"
    for agente in ("YFinance", "Analyzer", "Investigator"):
        assert sum(m.name == agente for m in msgs) == sum(p["agente"] == agente for p in fx["passagens"]), agente
    assert next(p for p in fx["passagens"] if p["agente"] == "YFinance")["tools"]
    if caminho.stem in INVESTIGATOR_ESPERADO:
        assert any(m.name == "Investigator" for m in msgs) == INVESTIGATOR_ESPERADO[caminho.stem]


@pytest.mark.parametrize("caminho", _parametros(marcar_corte=True))
def test_contexto_cabe_no_orcamento_do_juiz(caminho):
    """Confere que limitar_fontes não corta nada nesta fixture: nenhum item de contexto_do_agente
    (passagens do Analyzer e do Investigator) ou de montar_insumos passa de MAX_CHARS_POR_FONTE,
    e nenhuma lista passa de MAX_FONTES.

    Corte silencioso deixa o juiz com menos do que o agente teve (foi o que manteve um eval em xfail na
    referência). O ponto mais exposto é o bloco do Investigator nos insumos: o Consolidador o copia
    literalmente, então um rabo cortado vira idk garantido no Faithfulness dele."""
    fx = carregar_fixture(caminho)
    listas = [contexto_do_agente(fx, p["agente"], p["n"]) for p in fx["passagens"] if p["agente"] in ("Analyzer", "Investigator")]
    listas.append(montar_insumos(mensagens(fx)))
    for lista in listas:
        assert len(lista) <= MAX_FONTES
        maior = max(lista, key=len)
        assert len(maior) <= MAX_CHARS_POR_FONTE, f"{len(maior)} caracteres: {maior[:80]}"


def test_estado_pula_sem_fixture(tmp_path):
    """Confere que, sem o arquivo, a carga da fixture pula com a instrução de como gerar."""
    with pytest.raises(pytest.skip.Exception, match="make eval-fixtures"):
        carregar_fixture(tmp_path / "nao_existe.json")
