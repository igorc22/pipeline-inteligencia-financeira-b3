from unittest.mock import patch

import pytest
from langchain_core.messages import HumanMessage

from fluxo_financeiro.agents.consolidator import (
    CONSOLIDADOR_PROMPT,
    LIMITACAO_PERFIL_RESERVA,
    LIMITACAO_SEM_DADOS,
    LIMITACAO_SEM_NOTICIAS,
    LIMITACAO_SEM_SETOR,
    consolidar,
    formatar_relatorio,
    montar_insumos,
    relatorio_de_emergencia,
)
from fluxo_financeiro.shared.types import ErroAgente, RelatorioFinal
from fluxo_financeiro.tools.financial_data import AVISO_PERFIL_RESERVA

REL = RelatorioFinal(
    resumo="Lucro caiu.",
    indicadores=["P/L: 74,7x"],
    contexto="Minério em queda.",
    riscos=["Preço do minério"],
    limitacoes=["Sem notícias do setor"],
    diagnostico="- Causa identificada: impairment",
)


# ---------------------------------------------------------------------------
# formatar_relatorio (markdown montado em código)
# ---------------------------------------------------------------------------

def test_formatar_relatorio_tem_secoes_na_ordem():
    """Confere que o relatório tem título com o ticker e as seções na ordem fixa."""
    md = formatar_relatorio(REL, "VALE3")

    assert md.startswith("# Relatório: VALE3")
    titulos = ["## Resumo", "## Indicadores", "## Notícias e setor",
               "## Diagnóstico da anomalia", "## Riscos", "## Limitações"]
    posicoes = [md.index(t) for t in titulos]
    assert posicoes == sorted(posicoes)
    assert "- P/L: 74,7x" in md


def test_formatar_relatorio_sem_diagnostico_omite_secao():
    """Confere que, sem Investigator, a seção de diagnóstico não aparece."""
    md = formatar_relatorio(REL.model_copy(update={"diagnostico": None}), "WEGE3")

    assert "Diagnóstico" not in md


def test_formatar_relatorio_omite_secoes_vazias():
    """Confere que lista vazia não vira título solto no relatório."""
    md = formatar_relatorio(REL.model_copy(update={"indicadores": [], "riscos": [], "limitacoes": []}), "WEGE3")

    assert "## Indicadores" not in md
    assert "## Riscos" not in md
    assert "## Limitações" not in md


def test_formatar_relatorio_sem_ticker():
    """Confere que, sem ticker identificado, o título é genérico."""
    assert formatar_relatorio(REL, None).startswith("# Relatório da análise")


# ---------------------------------------------------------------------------
# relatorio_de_emergencia (fallback quando o LLM do Consolidador falha)
# ---------------------------------------------------------------------------

def test_relatorio_de_emergencia_junta_so_os_agentes():
    """Confere que o fallback junta só as respostas dos workers, sem tarefas nem o pedido."""
    msgs = [
        HumanMessage("Analise VALE3"),
        HumanMessage("dados X", name="YFinance"),
        HumanMessage("Busque notícias", name="Supervisor"),
        HumanMessage("notícias Y", name="Analyzer"),
    ]

    texto = relatorio_de_emergencia(msgs)

    assert texto.startswith("> Não foi possível consolidar")
    assert "dados X" in texto and "notícias Y" in texto
    assert "Busque notícias" not in texto
    assert "Analise VALE3" not in texto


# ---------------------------------------------------------------------------
# consolidar (LLM mockado; o pós-processamento em código é o que se testa)
# ---------------------------------------------------------------------------

HIST = [
    HumanMessage("Analise VALE3"),
    HumanMessage("P/L 74,7x", name="YFinance"),
    HumanMessage("Busque notícias", name="Supervisor"),
    HumanMessage("Minério caiu", name="Analyzer"),
    HumanMessage("Busque o setor", name="Supervisor"),
    HumanMessage("Setor fraco", name="Analyzer"),
]
DIAG = "- Causa identificada: impairment de níquel\n- Natureza do evento: pontual"
# Os campos são escritos à mão (não derivados das mensagens): o Consolidador decide por eles.
ESTADO = {"messages": HIST, "dados_mercado": "P/L 74,7x", "noticias": "Minério caiu", "contexto_setor": "Setor fraco"}
VAZIO = {"messages": [HumanMessage("Analise VALE3")]}


@pytest.fixture
def mock_llm():
    """LLM do Consolidador mockado: devolve uma cópia de REL (que vem com diagnóstico preenchido)."""
    with patch("fluxo_financeiro.agents.consolidator.llm") as llm:
        llm.with_structured_output.return_value.invoke.side_effect = lambda _msgs: REL.model_copy()
        yield llm


def _enviado(mock_llm):
    """(system prompt, insumos) que foram mandados ao LLM."""
    enviadas = mock_llm.with_structured_output.return_value.invoke.call_args.args[0]
    return enviadas[0].content, enviadas[-1].content


def test_consolidar_envia_so_respostas_dos_agentes(mock_llm):
    """Confere que o LLM recebe o prompt e as respostas dos workers, sem as tarefas do Supervisor."""
    consolidar(ESTADO)

    mock_llm.with_structured_output.assert_called_once_with(RelatorioFinal)
    system, insumos = _enviado(mock_llm)
    assert system == CONSOLIDADOR_PROMPT
    assert "P/L 74,7x" in insumos and "Setor fraco" in insumos
    assert "Busque notícias" not in insumos and "Busque o setor" not in insumos


def test_montar_insumos_um_bloco_por_resposta(mock_llm):
    """Confere que montar_insumos devolve o pedido e um bloco por resposta de agente, sem as tarefas do Supervisor."""
    blocos = montar_insumos([HumanMessage("Analise VALE3"), HumanMessage("d", name="YFinance"),
                             HumanMessage("t", name="Supervisor"), HumanMessage("a1", name="Analyzer")])
    assert len(blocos) == 3
    assert blocos[0] == "<pedido_usuario>Analise VALE3</pedido_usuario>"
    assert blocos[2].startswith('<resposta_agente nome="Analyzer" n="1">')


def test_consolidar_envia_os_insumos_juntos(mock_llm):
    """Confere que o texto que vai ao LLM é a junção dos blocos de montar_insumos (os evals medem contra ela)."""
    messages = [HumanMessage("Analise VALE3"), HumanMessage("d", name="YFinance")]
    consolidar({"messages": messages, "dados_mercado": "d"})
    _, insumos = _enviado(mock_llm)
    assert insumos == "\n\n".join(montar_insumos(messages))


def test_consolidar_copia_diagnostico_do_investigator_literalmente(mock_llm):
    """Confere que o diagnóstico é o texto do Investigator, mesmo se o LLM escrever outro."""
    mock_llm.with_structured_output.return_value.invoke.side_effect = (
        lambda _msgs: REL.model_copy(update={"diagnostico": "resumo inventado"})
    )

    relatorio = consolidar({**ESTADO, "messages": HIST + [HumanMessage(DIAG, name="Investigator")],
                            "diagnostico": DIAG})

    assert relatorio.diagnostico == DIAG


def test_consolidar_sem_investigator_zera_diagnostico(mock_llm):
    """Confere que, sem o campo diagnostico, o diagnóstico fica nulo."""
    assert consolidar(ESTADO).diagnostico is None


def test_diagnostico_vem_do_campo(mock_llm):
    """Confere que o diagnóstico vem do campo do state, não de existir mensagem do Investigator."""
    so_campo = consolidar({**ESTADO, "diagnostico": DIAG})
    assert so_campo.diagnostico == DIAG

    so_mensagem = consolidar({**ESTADO, "messages": HIST + [HumanMessage(DIAG, name="Investigator")]})
    assert so_mensagem.diagnostico is None


def test_consolidar_aponta_etapas_que_faltaram(mock_llm):
    """Confere que etapas ausentes (hard stop, falha) viram limitações escritas em código."""
    sem_nada = consolidar(VAZIO)
    assert LIMITACAO_SEM_DADOS in sem_nada.limitacoes
    assert LIMITACAO_SEM_NOTICIAS in sem_nada.limitacoes

    completo = consolidar(ESTADO)
    assert LIMITACAO_SEM_DADOS not in completo.limitacoes
    assert LIMITACAO_SEM_NOTICIAS not in completo.limitacoes


def test_consolidar_zera_secoes_de_etapas_que_nao_rodaram(mock_llm):
    """Confere que, sem YFinance/Analyzer, indicadores e contexto do LLM são descartados (não finge ter dados)."""
    sem_nada = consolidar(VAZIO)  # REL vem com indicadores e contexto preenchidos
    assert sem_nada.indicadores == []
    assert sem_nada.contexto == ""

    completo = consolidar(ESTADO)
    assert completo.indicadores == REL.indicadores
    assert completo.contexto == REL.contexto


def test_consolidar_campo_vazio_conta_como_etapa_feita(mock_llm):
    """Confere que um campo gravado vazio (agente respondeu nada) conta como etapa feita, como a mensagem contava."""
    vazio = consolidar({**ESTADO, "dados_mercado": "", "noticias": "", "contexto_setor": ""})

    assert not {LIMITACAO_SEM_DADOS, LIMITACAO_SEM_NOTICIAS, LIMITACAO_SEM_SETOR} & set(vazio.limitacoes)


def test_consolidar_nao_repete_limitacoes(mock_llm):
    """Confere que limitações iguais (a menos de espaços nas pontas) aparecem uma vez, na ordem."""
    mock_llm.with_structured_output.return_value.invoke.side_effect = lambda _m: REL.model_copy(
        update={"limitacoes": [LIMITACAO_SEM_DADOS + " ", "Sem fatos relevantes", "Sem fatos relevantes"]})

    lim = consolidar(VAZIO).limitacoes

    assert lim == [LIMITACAO_SEM_DADOS, "Sem fatos relevantes", LIMITACAO_SEM_NOTICIAS]


def test_consolidar_aponta_setor_que_faltou(mock_llm):
    """Confere que notícias sem contexto do setor vira limitação de setor; sem notícias ou com os dois, não."""
    uma = {"messages": HIST[:4], "dados_mercado": "P/L 74,7x", "noticias": "Minério caiu"}
    assert LIMITACAO_SEM_SETOR in consolidar(uma).limitacoes
    assert consolidar(uma).contexto == REL.contexto  # o que o Analyzer trouxe continua

    assert LIMITACAO_SEM_SETOR not in consolidar(ESTADO).limitacoes

    sem_analyzer = consolidar(VAZIO).limitacoes
    assert LIMITACAO_SEM_SETOR not in sem_analyzer and LIMITACAO_SEM_NOTICIAS in sem_analyzer


def test_limitacoes_pelos_campos_hard_stop(mock_llm):
    """Confere que, num hard stop antes do Analyzer terminar, as limitações saem dos campos e não das mensagens."""
    # Só os dados de mercado: faltam notícias e setor, mesmo com mensagens do Analyzer no histórico.
    so_dados = consolidar({"messages": HIST, "dados_mercado": "P/L 74,7x"})
    assert LIMITACAO_SEM_NOTICIAS in so_dados.limitacoes
    assert LIMITACAO_SEM_SETOR not in so_dados.limitacoes
    assert so_dados.contexto == ""

    # Dados e notícias, com duas mensagens do Analyzer (retry) mas sem o campo do setor.
    sem_setor = consolidar({"messages": HIST, "dados_mercado": "P/L 74,7x", "noticias": "Minério caiu"})
    assert LIMITACAO_SEM_SETOR in sem_setor.limitacoes
    assert LIMITACAO_SEM_NOTICIAS not in sem_setor.limitacoes


def test_consolidar_anota_perfil_da_reserva(mock_llm):
    """Confere que o aviso da reserva nos dados de mercado vira limitação escrita em código."""
    dados = f"P/L 74,7x\n{AVISO_PERFIL_RESERVA}"
    hist = [HumanMessage("Analise VALE3"), HumanMessage(dados, name="YFinance")] + HIST[2:]

    assert LIMITACAO_PERFIL_RESERVA in consolidar({**ESTADO, "messages": hist, "dados_mercado": dados}).limitacoes


def test_consolidar_sem_aviso_nao_anota_reserva(mock_llm):
    """Confere que, com a Brapi tendo respondido (sem o aviso), a limitação da reserva não aparece."""
    assert LIMITACAO_PERFIL_RESERVA not in consolidar(ESTADO).limitacoes


def test_limitacao_de_agente_que_desistiu(mock_llm):
    """Confere que cada agente que desistiu (temporário no limite ou permanente) vira uma limitação escrita em código."""
    estado = {
        **ESTADO,
        "contexto_setor": None,
        "erros": {
            "Analyzer": ErroAgente(tipo="transitorio", mensagem="TimeoutError: lento", tentativas=2),
            "Investigator": ErroAgente(tipo="permanente", mensagem="ValueError: chave", tentativas=1),
            "YFinance": None,  # falhou e depois acertou: não é limitação
        },
        "tentativas": {"Analyzer": 2, "Investigator": 1, "YFinance": 0},
    }

    lim = consolidar(estado).limitacoes

    assert "O Analyzer falhou depois de 2 tentativas (erro temporário): a etapa ficou de fora." in lim
    assert "O Investigator falhou depois de 1 tentativa (erro permanente): a etapa ficou de fora." in lim
    assert LIMITACAO_SEM_SETOR in lim
    assert not any(l.startswith("O YFinance") for l in lim)


def test_erro_temporario_abaixo_do_limite_nao_vira_limitacao(mock_llm):
    """Confere que um erro temporário que ainda seria reenviado (hard stop no meio) não vira limitação de desistência."""
    estado = {**ESTADO, "erros": {"Analyzer": ErroAgente(tipo="transitorio", mensagem="x", tentativas=1)},
              "tentativas": {"Analyzer": 1}}

    assert not any("falhou depois de" in l for l in consolidar(estado).limitacoes)


ERRO_INVESTIGATOR = HumanMessage(
    "Erro: Investigator falhou depois de 2 tentativas (transitorio): TimeoutError: lento", name="Investigator"
)


def test_erro_superado_nao_vai_aos_insumos(mock_llm):
    """Confere que o erro de uma rodada que o reenvio superou não vira insumo: o diagnóstico real é o n=1."""
    messages = [HumanMessage("Analise VALE3"), ERRO_INVESTIGATOR, HumanMessage(DIAG, name="Investigator")]

    consolidar({"messages": messages, "diagnostico": DIAG,
                "erros": {"Investigator": None}, "tentativas": {"Investigator": 0}})

    _, insumos = _enviado(mock_llm)
    assert "falhou depois de" not in insumos
    assert '<resposta_agente nome="Investigator" n="1">' in insumos
    assert 'n="2"' not in insumos


def test_so_o_erro_superado_sai_dos_insumos():
    """Confere que, no Analyzer, o erro das notícias recuperadas sai e o do setor, que desistiu, fica."""
    erro_noticias = HumanMessage("Erro: Analyzer falhou depois de 2 tentativas (transitorio): TimeoutError: a", name="Analyzer")
    erro_setor = HumanMessage("Erro: Analyzer falhou depois de 1 tentativa (permanente): ValueError: b", name="Analyzer")
    blocos = montar_insumos([HumanMessage("Analise VALE3"), erro_noticias,
                             HumanMessage("notícias", name="Analyzer"), erro_setor])

    texto = "\n".join(blocos)
    assert "TimeoutError: a" not in texto
    assert "ValueError: b" in texto
    assert blocos[1].startswith('<resposta_agente nome="Analyzer" n="1">\nnotícias')


def test_relatorio_de_emergencia_sem_erro_superado():
    """Confere que o fallback sem LLM também deixa de fora o erro que o reenvio superou."""
    texto = relatorio_de_emergencia([HumanMessage("Analise VALE3"), ERRO_INVESTIGATOR,
                                     HumanMessage(DIAG, name="Investigator")])

    assert "falhou depois de" not in texto
    assert DIAG in texto


def test_consolidar_erro_do_llm_sobe(mock_llm):
    """Confere que erro do LLM sobe: quem decide o fallback é o nó do grafo."""
    mock_llm.with_structured_output.return_value.invoke.side_effect = Exception("429")

    with pytest.raises(Exception, match="429"):
        consolidar(ESTADO)
