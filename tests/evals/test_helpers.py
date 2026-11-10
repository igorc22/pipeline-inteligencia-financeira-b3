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

from fluxo_financeiro.agents.consolidator import montar_insumos
from tests.evals.helpers import (
    CABECALHO,
    FIXTURES_DIR,
    carregar_fixture,
    contexto_do_agente,
    despejar,
    formatar,
    limitar_fontes,
    medir_e_registrar,
    mensagens,
    nota_rigida,
    registrar,
    registrar_erro,
    resposta_do_agente,
    sem_sumario,
    tarefa_do_supervisor,
)

HIST = [
    HumanMessage("Analise a ação VALE3"),
    HumanMessage("Colete os dados da VALE3", name="Supervisor"),
    HumanMessage("P/L 5,2", name="YFinance"),
    HumanMessage("Busque notícias e setor da VALE3", name="Supervisor"),
    HumanMessage("Investigue a anomalia na queda de lucro", name="Supervisor"),
    HumanMessage("notícias e setor", name="Analyzer"),
    HumanMessage("Causa identificada: impairment", name="Investigator"),
]
PASSAGENS = [
    {"agente": "YFinance", "n": 1, "tools": [{"nome": "buscar_dados_acao_b3", "conteudo": "P/L 5,2"}]},
    {"agente": "Analyzer", "n": 1, "tools": [{"nome": "buscar_noticias_web", "conteudo": "n1"}]},
]
PESQUISA = {
    "perguntas": ["Por que o lucro caiu?", "Houve impairment?", "O minério caiu?"],
    "achados": [
        {"pergunta": "Por que o lucro caiu?", "rodada": 1, "texto": "impairment de US$ 1 bi\nFontes: vale.com"},
        {"pergunta": "Houve impairment?", "rodada": 1, "texto": ""},
        {"pergunta": "O minério caiu?", "rodada": 2, "texto": "minério a US$ 95"},
    ],
    "voltas": 1,
    "historico": "Net Income 4T25: -3.8B",
}


def _estado(messages=HIST, passagens=PASSAGENS, pesquisa=PESQUISA):
    return {"messages": messages_to_dict(messages), "passagens": passagens, "pesquisa": pesquisa}


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


def test_limitar_fontes_preserva_textos_dentro_do_orcamento():
    """Confere que textos que cabem no orçamento passam iguais e na mesma ordem."""
    textos = ["a", "bb", "ccc"]
    assert limitar_fontes(textos) == textos


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


def test_contexto_do_analyzer_tem_as_tools_e_o_historico_do_ramo():
    """Confere que o contexto do Analyzer traz as tools dele, o pedido, o YFinance e a própria tarefa,
    sem a tarefa do Investigator (que veio junto, no paralelo) e sem respostas de agentes."""
    ctx = contexto_do_agente(_estado(), "Analyzer")
    assert ctx[0] == "buscar_noticias_web: n1"
    assert {"Usuario: Analise a ação VALE3", "YFinance: P/L 5,2", "Supervisor: Busque notícias e setor da VALE3"} <= set(ctx)
    assert not any("Investigue" in c or c.startswith("Analyzer:") for c in ctx)


def test_contexto_de_passagem_sem_tools_e_so_o_historico():
    """Confere que passagem sem tool não quebra: o contexto é só o histórico permitido."""
    passagens = [PASSAGENS[0], {"agente": "Analyzer", "n": 1, "tools": []}]
    assert contexto_do_agente(_estado(passagens=passagens), "Analyzer") == [
        "Usuario: Analise a ação VALE3", "Supervisor: Colete os dados da VALE3", "YFinance: P/L 5,2",
        "Supervisor: Busque notícias e setor da VALE3"]


def test_contexto_do_investigator_e_o_que_o_subgrafo_leu():
    """Confere que o contexto do Investigator é a tarefa dele (sem a do Analyzer), o histórico trimestral e um
    item por achado com texto, e nada do pedido ou da resposta do YFinance."""
    assert contexto_do_agente(_estado(), "Investigator") == [
        "Supervisor: Investigue a anomalia na queda de lucro",
        "buscar_historico_trimestral: Net Income 4T25: -3.8B",
        "pesquisa (Por que o lucro caiu?): impairment de US$ 1 bi\nFontes: vale.com",
        "pesquisa (O minério caiu?): minério a US$ 95",
    ]


def test_contexto_do_investigator_sem_historico_nem_tarefa():
    """Confere que histórico trimestral vazio e falta de tarefa não viram itens vazios no contexto."""
    msgs = [HumanMessage("Analise a ação VALE3"), HumanMessage("Causa identificada: x", name="Investigator")]
    estado = _estado(msgs, [], {**PESQUISA, "historico": "", "achados": PESQUISA["achados"][:1]})
    assert contexto_do_agente(estado, "Investigator") == [
        "pesquisa (Por que o lucro caiu?): impairment de US$ 1 bi\nFontes: vale.com"]


def test_resposta_do_agente_ausente_devolve_none():
    """Confere que fixture sem Investigator devolve None (os evals dele pulam)."""
    sem_investigator = _estado(HIST[:4] + [HIST[5]], PASSAGENS, None)
    assert resposta_do_agente(sem_investigator, "Investigator") is None
    assert tarefa_do_supervisor(sem_investigator, "Investigator") is None
    assert resposta_do_agente(sem_investigator, "Analyzer") == "notícias e setor"


def test_tarefa_do_supervisor_com_tarefas_paralelas_adjacentes():
    """Confere que, com as tarefas do Analyzer e do Investigator lado a lado no histórico, cada um acha a sua,
    em qualquer ordem de resposta."""
    for historico in (HIST, HIST[:5] + [HIST[6], HIST[5]]):  # o Investigator pode responder antes
        estado = _estado(historico)
        assert tarefa_do_supervisor(estado, "Analyzer") == "Busque notícias e setor da VALE3"
        assert tarefa_do_supervisor(estado, "Investigator") == "Investigue a anomalia na queda de lucro"


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


def test_medir_e_registrar_metrica_que_reprova(tmp_path):
    """Confere que nota reprovada é registrada, despejada com o contexto do juiz e falha o teste."""
    with pytest.raises(pytest.fail.Exception, match="entrada, saída e contexto em"):
        medir_e_registrar(MetricaFalsa(0.4), TC, "vale3", "t", "juiz-x", caminho=tmp_path / "n.csv", diretorio=tmp_path / "f")
    assert list(csv.DictReader((tmp_path / "n.csv").open(encoding="utf-8")))[0]["passou"] == "False"
    despejo = next((tmp_path / "f").iterdir()).read_text(encoding="utf-8")
    assert "trecho-do-contexto-1" in despejo


# ---------------------------------------------------------------------------
# Nota rígida da fidelidade (segunda nota, sem portão)
# ---------------------------------------------------------------------------

def _veredito(texto):
    return SimpleNamespace(verdict=texto, reason="r")


def test_nota_rigida_conta_so_yes():
    """Confere que só 'yes' conta (sem diferenciar maiúsculas e espaços): 'idk' e 'no' pesam igual contra."""
    metric = _metrica(claims=["a", "b", "c"], verdicts=[_veredito("yes"), _veredito("idk"), _veredito("no")])
    assert nota_rigida(metric) == pytest.approx(1 / 3)

    metric = _metrica(claims=["a", "b"], verdicts=[_veredito("Yes "), _veredito("idk")])
    assert nota_rigida(metric) == 0.5


def test_nota_rigida_vazia_e_outras_metricas():
    """Confere que fidelidade sem vereditos vale 1.0 e que métrica sem claims (GEval, Answer Relevancy) dá None."""
    assert nota_rigida(_metrica(claims=[], verdicts=[])) == 1.0
    assert nota_rigida(_metrica(**{"__name__": "Neutralidade [GEval]"})) is None
    assert nota_rigida(_metrica(verdicts=[_veredito("yes")])) is None


class FidelidadeFalsa(MetricaFalsa):
    """Imita a Faithfulness: além da nota, guarda as afirmações e os vereditos que o juiz devolveu."""
    def __init__(self, nota, vereditos, threshold=0.8):
        super().__init__(nota, threshold=threshold)
        self.__name__ = "Faithfulness"
        self.claims = [f"afirmação {i}" for i in range(len(vereditos))]
        self.verdicts = [_veredito(v) for v in vereditos]


def test_medir_registra_nota_rigida_sem_reprovar(tmp_path):
    """Confere que a fidelidade ganha uma segunda linha rígida no CSV e que ela nunca reprova o teste.

    A normal passa (1.0) e a rígida fica em 0.5, abaixo do threshold: o teste segue passando, sem despejo.
    """
    medir_e_registrar(FidelidadeFalsa(1.0, ["yes", "idk"]), TC, "vale3", "t", "juiz-x",
                      caminho=tmp_path / "n.csv", diretorio=tmp_path / "f")

    linhas = list(csv.DictReader((tmp_path / "n.csv").open(encoding="utf-8")))
    assert len(linhas) == 2
    assert linhas[0]["metrica"] == "Faithfulness" and linhas[0]["passou"] == "True"
    rigida = linhas[1]
    assert rigida["metrica"] == "Faithfulness (rígida)"
    assert float(rigida["nota"]) == 0.5
    assert rigida["threshold"] == "0.8"
    assert rigida["passou"] == "False"
    assert rigida["custo_usd"] == "0"
    assert rigida["juiz"] == "juiz-x"
    assert not (tmp_path / "f").exists()


def test_medir_registra_nota_rigida_mesmo_quando_a_normal_reprova(tmp_path):
    """Confere que a linha rígida entra no CSV antes da reprovação da normal, e que a falha vem só da normal."""
    with pytest.raises(pytest.fail.Exception):
        medir_e_registrar(FidelidadeFalsa(0.5, ["yes", "no"]), TC, "vale3", "t", "juiz-x",
                          caminho=tmp_path / "n.csv", diretorio=tmp_path / "f")
    linhas = list(csv.DictReader((tmp_path / "n.csv").open(encoding="utf-8")))
    assert [l["metrica"] for l in linhas] == ["Faithfulness", "Faithfulness (rígida)"]


# ---------------------------------------------------------------------------
# sem_sumario: a cobertura do Consolidador sem o sumário do negócio
# ---------------------------------------------------------------------------

ANTES = "Dados para WEGE3.SA:\nP/L:  32.3x\nSetor: Bens Industriais\nSumario de Negócio:\n"
DEPOIS = (
    "Histórico Recente (Últimos 5 dias de fechamento):\nDate\n2026-11-06    48.19\n"
    "Fonte: cotação e perfil da Brapi; P/L, ROE, DY e histórico do yfinance.\n"
)
SUMARIO = "A WEG S.A. foi fundada em 1961, com sede em Jaraguá do Sul (SC).\n\nFabrica motores elétricos."


@pytest.mark.parametrize("origem", ["brapi", "yfinance"])
def test_sem_sumario_tira_o_bloco(origem):
    """Confere que o cabeçalho e o bloco da tag saem, com qualquer origem, e o que vem antes e depois fica."""
    texto = ANTES + f'<conteudo_externo origem="{origem}">\n{SUMARIO}\n</conteudo_externo>\n' + DEPOIS

    saida = sem_sumario(texto)

    assert saida == "Dados para WEGE3.SA:\nP/L:  32.3x\nSetor: Bens Industriais\n" + DEPOIS


def test_sem_sumario_tira_o_bloco_escapado():
    """Confere que a tag escapada (como montar_insumos deixa uma tag que o agente repassou) também sai."""
    texto = ANTES + f'&lt;conteudo_externo origem="brapi"&gt;\n{SUMARIO}\n&lt;/conteudo_externo&gt;\n' + DEPOIS

    assert sem_sumario(texto) == "Dados para WEGE3.SA:\nP/L:  32.3x\nSetor: Bens Industriais\n" + DEPOIS


def test_sem_sumario_tira_o_texto_sem_tag():
    """Confere que o formato real das fixtures corta do cabeçalho até o Histórico Recente e tira o sumário."""
    texto = ANTES + SUMARIO + "\n" + DEPOIS + "\nPiotroski F-Score para WEGE3.SA: 5/9\n"

    saida = sem_sumario(texto)

    assert "fundada em 1961" not in saida and "Sumario de Negócio" not in saida
    assert saida.startswith("Dados para WEGE3.SA:\nP/L:  32.3x\nSetor: Bens Industriais\nHistórico Recente")
    assert saida.endswith("Piotroski F-Score para WEGE3.SA: 5/9\n")


def test_sem_sumario_na_fixture_da_wege3():
    """Confere que, nos insumos reais da fixture da WEGE3, o sumário sai e os dados do YFinance ficam."""
    estado = carregar_fixture(FIXTURES_DIR / "wege3.json")
    insumos = [sem_sumario(t) for t in montar_insumos(mensagens(estado))]
    yfinance = next(t for t in insumos if 'nome="YFinance"' in t)

    assert "fundada em 1961" not in yfinance
    assert "Histórico Recente" in yfinance
    assert "Piotroski" in yfinance
    assert "Sharpe" in yfinance


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
    """Confere que, pela árvore sintática, nenhum módulo de tests/evals importa deepeval no topo:
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
