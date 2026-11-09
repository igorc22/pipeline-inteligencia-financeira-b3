"""Evals do Analyzer: passagem única (notícias da empresa e contexto do setor).

Risco coberto: o Analyzer escrever fato ou número que não veio da busca nem do que ele tinha no
histórico (pedido, dados do YFinance, tarefas do Supervisor) -> Faithfulness da resposta única.

O contexto da passagem é o de contexto_do_agente: as saídas das tools da passagem, mais as
fontes primárias do histórico.

Nada da deepeval no topo do módulo: a coleta importa este arquivo em todo pytest, fora do bloqueio de rede.
"""
import pytest

from tests.evals.helpers import contexto_do_agente, limitar_fontes, resposta_do_agente, tarefa_do_supervisor

pytestmark = [pytest.mark.eval, pytest.mark.enable_socket]


def test_faithfulness_analyzer(juiz, estado, medir):
    """Confere que o que o Analyzer afirma na sua passagem única está nas buscas dela ou nas fontes primárias do histórico.

    threshold 0,8 e não 1,0: o juiz é pedante com arredondamento ("P/L 5,2" contra 5,2134 conta como
    afirmação não fiel). Reprovação é lida veredito a veredito no despejo de _falhas/.
    """
    from deepeval.metrics import FaithfulnessMetric
    from deepeval.test_case import LLMTestCase

    resposta = resposta_do_agente(estado, "Analyzer", 1)
    assert resposta is not None, "fixture sem a passagem do Analyzer"
    tc = LLMTestCase(
        input=tarefa_do_supervisor(estado, "Analyzer", 1),
        actual_output=resposta,
        retrieval_context=limitar_fontes(contexto_do_agente(estado, "Analyzer", 1)),
    )
    medir(FaithfulnessMetric(threshold=0.8, model=juiz), tc)
