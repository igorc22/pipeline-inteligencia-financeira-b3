"""Testes das funções puras de tests/evals/helpers.py.

Offline: não importam a deepeval, só imitam (duck typing) o que uma métrica dela devolveria. Por isso
não levam o marcador eval e rodam na suíte padrão, sem rede e sem gastar nada.
"""
import ast
import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, messages_to_dict

from tests.evals.helpers import (
    AVISO_LIMITE,
    CABECALHO,
    carregar_fixture,
    contexto_do_agente,
    despejar,
    formatar,
    limitar_fontes,
    medir_e_registrar,
    registrar,
    registrar_erro,
    resposta_do_agente,
    tarefa_do_supervisor,
)

HIST = [
    HumanMessage("Analise a ação VALE3"),
    HumanMessage("Colete os dados da VALE3", name="Supervisor"),
    HumanMessage("P/L 5,2", name="YFinance"),
    HumanMessage("Busque notícias da VALE3", name="Supervisor"),
    HumanMessage("a1: minério caiu", name="Analyzer"),
    HumanMessage("Busque o setor", name="Supervisor"),
    HumanMessage("a2: setor de mineração", name="Analyzer"),
    HumanMessage("Investigue a queda de 40%", name="Supervisor"),
    HumanMessage("Causa identificada: impairment", name="Investigator"),
]
PASSAGENS = [
    {"agente": "YFinance", "n": 1, "tools": [{"nome": "buscar_dados_acao_b3", "conteudo": "P/L 5,2"}]},
    {"agente": "Analyzer", "n": 1, "tools": [{"nome": "buscar_noticias_web", "conteudo": "n1"}]},
    {"agente": "Analyzer", "n": 2, "tools": [{"nome": "buscar_noticias_web", "conteudo": "s1"}]},
    {"agente": "Investigator", "n": 1, "tools": [
        {"nome": "buscar_fatos_relevantes", "conteudo": "impairment de US$ 1 bi"},
        {"nome": "buscar_noticias_web", "conteudo": "Tool call limit exceeded. Do not call it again."}]},
]


def _estado(messages=HIST, passagens=PASSAGENS):
    return {"messages": messages_to_dict(messages), "passagens": passagens}


class MetricaFalsa:
    """Imita o que registrar, formatar e despejar leem de uma métrica da deepeval
    (na referência: __name__, score, threshold, success, reason)."""
    def __init__(self, nota, threshold=0.7, erro=None):
        self.__name__ = "MetricaFalsa"
        self.nota, self.threshold, self.erro = nota, threshold, erro
        self.score, self.success, self.reason, self.evaluation_cost = None, None, "motivo", 0.001
    def measure(self, tc):
        if self.erro:
            raise self.erro
        self.score = self.nota
        self.success = self.score >= self.threshold


TC = SimpleNamespace(input="tarefa", actual_output="saída", retrieval_context=["trecho-do-contexto-1"])


def _metrica(**kwargs):
    base = dict(score=0.5, threshold=0.8, success=False, evaluation_cost=None)
    base.update(kwargs)
    return SimpleNamespace(**base)


def _linhas(caminho):
    with open(caminho, encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


# ---------------------------------------------------------------------------
# Portados da referência (registrar, registrar_erro, despejar, limitar_fontes, formatar)
# ---------------------------------------------------------------------------

def test_registrar_escreve_cabecalho_uma_vez(tmp_path):
    """Confere que o cabeçalho, com custo_usd e juiz, entra só na primeira linha do CSV."""
    caminho = tmp_path / "notas.csv"
    metric = _metrica(**{"__name__": "Faithfulness"})

    registrar("vale3", "test_x", metric, "juiz-x", caminho=caminho)
    registrar("vale3", "test_y", metric, "juiz-x", caminho=caminho)

    linhas = _linhas(caminho)
    assert linhas[0] == CABECALHO
    assert CABECALHO == ["data", "fixture", "teste", "metrica", "nota", "threshold", "passou", "custo_usd", "juiz"]
    assert len(linhas) == 3


def test_registrar_grava_campos_da_metrica(tmp_path):
    """Confere que nota, threshold, resultado, custo e juiz saem da métrica e do argumento."""
    caminho = tmp_path / "notas.csv"
    metric = _metrica(**{"__name__": "Faithfulness"}, score=0.42, threshold=0.8, success=False, evaluation_cost=0.0021)

    registrar("vale3", "test_x", metric, "gemini-2.5-flash", caminho=caminho)

    with open(caminho, encoding="utf-8", newline="") as f:
        linha = list(csv.DictReader(f))[0]
    assert linha["fixture"] == "vale3"
    assert linha["teste"] == "test_x"
    assert linha["metrica"] == "Faithfulness"
    assert linha["nota"] == "0.42"
    assert linha["threshold"] == "0.8"
    assert linha["passou"] == "False"
    assert linha["custo_usd"] == "0.0021"
    assert linha["juiz"] == "gemini-2.5-flash"


def test_registrar_erro_grava_linha_de_erro(tmp_path):
    """Confere que measure() que quebra (timeout, rate limit) deixa rastro no CSV com passou=erro.

    Sem isso, a tentativa some do notas.csv: foi o que aconteceu na referência com um timeout de 88,5 s
    da deepeval no eval de cobertura do Consolidador.
    """
    caminho = tmp_path / "notas.csv"

    registrar_erro("vale3", "test_cobertura_consolidador", TimeoutError("call timed out after 88.5s"), "juiz-x",
                   caminho=caminho)

    with open(caminho, encoding="utf-8", newline="") as f:
        linha = list(csv.DictReader(f))[0]
    assert linha["fixture"] == "vale3"
    assert linha["teste"] == "test_cobertura_consolidador"
    assert linha["metrica"] == "TimeoutError"
    assert linha["passou"] == "erro"
    assert linha["juiz"] == "juiz-x"


def test_registrar_erro_usa_o_mesmo_cabecalho_de_registrar(tmp_path):
    """Confere que uma linha de erro e uma linha normal cabem no mesmo CSV."""
    caminho = tmp_path / "notas.csv"
    metric = _metrica(**{"__name__": "Faithfulness"})

    registrar("vale3", "test_ok", metric, "juiz-x", caminho=caminho)
    registrar_erro("vale3", "test_quebrou", ValueError("x"), "juiz-x", caminho=caminho)

    linhas = _linhas(caminho)
    assert linhas[0] == CABECALHO
    assert len(linhas) == 3
    assert all(len(linha) == len(CABECALHO) for linha in linhas)


def test_despejar_escreve_entrada_saida_e_caminho_do_arquivo(tmp_path):
    """Confere que o despejo traz entrada, saída e justificativa, e devolve o caminho do arquivo."""
    metric = _metrica(**{"__name__": "Neutralidade"}, reason="tom neutro insuficiente")
    tc = SimpleNamespace(input="pergunta", actual_output="resposta")

    caminho = despejar("vale3", "test_x", metric, tc, diretorio=tmp_path)

    assert caminho == tmp_path / "vale3-test_x.txt"
    conteudo = caminho.read_text(encoding="utf-8")
    assert "pergunta" in conteudo
    assert "resposta" in conteudo
    assert "tom neutro insuficiente" in conteudo


def test_despejar_numera_os_itens_do_contexto(tmp_path):
    """Confere que o despejo lista o retrieval_context um item por bloco numerado, para achar o trecho do juiz."""
    metric = _metrica(**{"__name__": "Faithfulness"}, reason=None)
    tc = SimpleNamespace(input="tarefa", actual_output="saída", retrieval_context=["primeiro trecho", "segundo trecho"])

    conteudo = despejar("vale3", "test_x", metric, tc, diretorio=tmp_path).read_text(encoding="utf-8")

    assert "[1]\nprimeiro trecho" in conteudo
    assert "[2]\nsegundo trecho" in conteudo


def test_limitar_fontes_corta_a_quantidade():
    """Confere que o corte é do orçamento do juiz, não da produção: sobram só max_fontes itens."""
    assert len(limitar_fontes([str(i) for i in range(30)], max_fontes=5)) == 5


def test_limitar_fontes_preserva_textos_dentro_do_orcamento():
    """Confere que textos que cabem no orçamento passam iguais e na mesma ordem."""
    textos = ["a", "bb", "ccc"]
    assert limitar_fontes(textos) == textos


def test_limitar_fontes_tolera_lista_vazia():
    """Confere que contexto vazio (nenhuma fonte) não quebra."""
    assert limitar_fontes([]) == []


def test_formatar_distingue_no_de_idk_em_faithfulness():
    """Confere que 'no' (contradiz a fonte) e 'idk' (a fonte não fala disso) saem com rótulos diferentes.

    Rótulos iguais escondiam a diferença: o texto que contradiz a fonte tem de mudar, o que a fonte
    não confirma pode estar certo mesmo assim.
    """
    metric = _metrica(
        **{"__name__": "Faithfulness"},
        reason=None,
        claims=["afirmação com contradição", "afirmação não confirmável"],
        verdicts=[
            SimpleNamespace(verdict="no", reason="contradiz a fonte"),
            SimpleNamespace(verdict="idk", reason="fonte não fala disso"),
        ],
    )

    saida = formatar(metric)

    assert "[contradiz] afirmação com contradição" in saida
    assert "[nao confirmado] afirmação não confirmável" in saida


def test_formatar_distingue_no_de_idk_em_summarization():
    """Confere que, no alinhamento da Summarization, só 'no' vira [contradiz] e 'idk' vira [nao confirmado]."""
    metric = _metrica(
        **{"__name__": "SummarizationMetric"},
        reason=None,
        score_breakdown={"Alignment": 0.5, "Coverage": 0.8},
        alignment_verdicts=[
            SimpleNamespace(verdict="no", reason="contradiz o original"),
            SimpleNamespace(verdict="idk", reason="original não menciona X"),
        ],
        coverage_verdicts=[],
    )

    saida = formatar(metric)

    assert "[contradiz] contradiz o original" in saida
    assert "[nao confirmado] original não menciona X" in saida


# ---------------------------------------------------------------------------
# Novos deste projeto
# ---------------------------------------------------------------------------

def test_limitar_fontes_corta_quantidade_e_tamanho():
    """Confere que o corte é do orçamento do juiz: no máximo max_fontes itens com no máximo max_chars cada."""
    assert limitar_fontes(["x" * 10] * 5, max_fontes=3, max_chars=4) == ["xxxx"] * 3


def test_contexto_do_agente_tem_tools_e_historico_permitido():
    """Confere que o contexto da 2ª passagem do Analyzer traz as tools dela, o pedido, o YFinance e as tarefas,
    e não as respostas anteriores do Analyzer nem a própria."""
    ctx = contexto_do_agente(_estado(), "Analyzer", 2)
    assert ctx[0] == "buscar_noticias_web: s1"
    assert {"Usuario: Analise a ação VALE3", "YFinance: P/L 5,2", "Supervisor: Busque o setor"} <= set(ctx)
    assert not any(c.startswith("Analyzer:") or "a1:" in c or "a2:" in c for c in ctx)
    assert "buscar_noticias_web: n1" not in ctx


def test_contexto_de_passagem_sem_tools_e_so_o_historico():
    """Confere que passagem sem tool não quebra: o contexto é só o histórico permitido."""
    passagens = [PASSAGENS[0], PASSAGENS[1], {"agente": "Analyzer", "n": 2, "tools": []}, PASSAGENS[3]]
    assert contexto_do_agente(_estado(passagens=passagens), "Analyzer", 2) == [
        "Usuario: Analise a ação VALE3", "Supervisor: Colete os dados da VALE3", "YFinance: P/L 5,2",
        "Supervisor: Busque notícias da VALE3", "Supervisor: Busque o setor"]


def test_contexto_tira_o_aviso_de_limite_de_buscas():
    """Confere que a ToolMessage de 'Tool call limit exceeded' não entra como evidência."""
    ctx = contexto_do_agente(_estado(), "Investigator")
    assert "buscar_fatos_relevantes: impairment de US$ 1 bi" in ctx
    assert not any(AVISO_LIMITE in c for c in ctx)


def test_resposta_do_agente_ausente_devolve_none():
    """Confere que fixture sem Investigator devolve None (os evals dele pulam)."""
    sem_investigator = _estado(HIST[:7], PASSAGENS[:3])
    assert resposta_do_agente(sem_investigator, "Investigator") is None
    assert tarefa_do_supervisor(sem_investigator, "Investigator") is None
    assert resposta_do_agente(sem_investigator, "Analyzer", 2) == "a2: setor de mineração"


def test_tarefa_do_supervisor_e_a_anterior_a_resposta():
    """Confere que a tarefa de cada agente é a mensagem do Supervisor logo antes da resposta dele."""
    assert tarefa_do_supervisor(_estado(), "Investigator") == "Investigue a queda de 40%"
    assert tarefa_do_supervisor(_estado(), "Analyzer", 1) == "Busque notícias da VALE3"
    assert tarefa_do_supervisor(_estado(), "Analyzer", 2) == "Busque o setor"


def test_carregar_fixture_le_utf8(tmp_path):
    """Confere que a fixture é lida em UTF-8, independente da localidade do Windows."""
    caminho = tmp_path / "x.json"
    caminho.write_text(json.dumps({"t": "≈ → 中 🙂"}, ensure_ascii=False), encoding="utf-8")
    assert carregar_fixture(caminho) == {"t": "≈ → 中 🙂"}


def test_medir_e_registrar_measure_que_quebra(tmp_path):
    """Confere que exceção do juiz vira linha 'erro' no CSV e é relançada, sem despejo."""
    with pytest.raises(TimeoutError):
        medir_e_registrar(MetricaFalsa(0.9, erro=TimeoutError("juiz")), TC, "vale3", "t", "juiz-x",
                          caminho=tmp_path / "n.csv", diretorio=tmp_path / "f")
    linhas = list(csv.DictReader((tmp_path / "n.csv").open(encoding="utf-8")))
    assert [l["passou"] for l in linhas] == ["erro"]
    assert not (tmp_path / "f").exists()


def test_medir_e_registrar_metrica_que_passa(tmp_path):
    """Confere que nota aprovada é registrada e não gera despejo nem falha."""
    medir_e_registrar(MetricaFalsa(0.9), TC, "vale3", "t", "juiz-x", caminho=tmp_path / "n.csv", diretorio=tmp_path / "f")
    linhas = list(csv.DictReader((tmp_path / "n.csv").open(encoding="utf-8")))
    assert len(linhas) == 1 and linhas[0]["nota"].startswith("0.9") and linhas[0]["juiz"] == "juiz-x"
    assert not (tmp_path / "f").exists()


def test_medir_e_registrar_metrica_que_reprova(tmp_path):
    """Confere que nota reprovada é registrada, despejada com o contexto do juiz e falha o teste."""
    with pytest.raises(pytest.fail.Exception, match="entrada, saída e contexto em"):
        medir_e_registrar(MetricaFalsa(0.4), TC, "vale3", "t", "juiz-x", caminho=tmp_path / "n.csv", diretorio=tmp_path / "f")
    assert list(csv.DictReader((tmp_path / "n.csv").open(encoding="utf-8")))[0]["passou"] == "False"
    despejo = next((tmp_path / "f").iterdir()).read_text(encoding="utf-8")
    assert "trecho-do-contexto-1" in despejo


def test_xfail_da_cobertura_nao_engole_erro_do_juiz(pytester):
    """Confere que, com xfail(raises=pytest.fail.Exception), nota baixa vira xfail e timeout do juiz reprova."""
    pytester.makepyfile(
        """
        import pytest
        MARCA = pytest.mark.xfail(raises=pytest.fail.Exception, strict=False, reason="r")

        @MARCA
        def test_nota_baixa():
            pytest.fail("nota 0,4")

        @MARCA
        def test_timeout():
            raise TimeoutError("juiz")
        """
    )
    resultado = pytester.runpytest_subprocess("-p", "no:cacheprovider", "-p", "no:deepeval")
    resultado.assert_outcomes(xfailed=1, failed=1)


def test_modulos_de_eval_nao_importam_deepeval_no_topo():
    """Confere, pela árvore sintática, que nenhum módulo de tests/evals importa deepeval no topo:
    a coleta importa todos, mesmo os evals desselecionados, e fora do bloqueio de rede."""
    arquivos = sorted(Path(__file__).parent.glob("*.py"))
    assert {"conftest.py", "helpers.py"} <= {a.name for a in arquivos}
    for arquivo in arquivos:
        for no in ast.parse(arquivo.read_text(encoding="utf-8")).body:
            if isinstance(no, ast.Import):
                nomes = [a.name for a in no.names]
            elif isinstance(no, ast.ImportFrom):
                nomes = [no.module or ""]
            else:
                continue
            assert not any(n.startswith("deepeval") for n in nomes), f"{arquivo.name}: {nomes}"
