"""Evals do Investigator, que só roda quando há anomalia (a fixture da WEGE3 não tem ele).

Dois riscos, um teste para cada:
  - afirmar fato que nenhuma busca trouxe                          -> Faithfulness
  - diagnóstico fraco: causa sem evidência, natureza incoerente com
    o histórico trimestral, ou causa inventada em vez de "não achei" -> GEval

O contexto é o de contexto_do_agente: com o subgrafo de pesquisa, a tarefa do Supervisor, o histórico
trimestral e os achados das buscas (o que o subgrafo leu). Em fixture antiga, as buscas da passagem (sem
o aviso de limite de buscas, que não é evidência) e as fontes primárias do histórico. As respostas do
Analyzer ficam de fora.

Nada da deepeval no topo do módulo: a coleta importa este arquivo em todo pytest, fora do bloqueio de rede.
"""
import pytest

from tests.evals.helpers import contexto_do_agente, limitar_fontes, resposta_do_agente, tarefa_do_supervisor

pytestmark = [pytest.mark.eval, pytest.mark.enable_socket]


@pytest.fixture(scope="session")
def investigacao(estado):
    """(tarefa, resposta, contexto) do Investigator, ou pula se a fixture não tem Investigator.

    O pulo não gasta nada: o juiz é criado antes (fixture de sessão), mas criar o GeminiModel não chama a API.
    """
    resposta = resposta_do_agente(estado, "Investigator")
    if resposta is None:
        pytest.skip("fixture sem Investigator")
    tarefa = tarefa_do_supervisor(estado, "Investigator")
    return tarefa, resposta, limitar_fontes(contexto_do_agente(estado, "Investigator"))


def test_faithfulness_investigator(juiz, investigacao, medir):
    """Confere que cada afirmação do diagnóstico está nos achados das buscas, no histórico trimestral ou na tarefa."""
    from deepeval.metrics import FaithfulnessMetric
    from deepeval.test_case import LLMTestCase

    tarefa, resposta, contexto = investigacao
    tc = LLMTestCase(input=tarefa, actual_output=resposta, retrieval_context=contexto)
    medir(FaithfulnessMetric(threshold=0.8, model=juiz), tc)


def test_diagnostico_investigator(juiz, investigacao, medir):
    """Confere que o diagnóstico explica a anomalia pedida com causa sustentada pelo contexto e natureza coerente.

    A Faithfulness não pega isto: um texto todo fiel às buscas pode não responder por que o número
    aconteceu, ou cravar "estrutural" contra um histórico que mostra um trimestre isolado.
    """
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCase, SingleTurnParams

    tarefa, resposta, contexto = investigacao
    tc = LLMTestCase(input=tarefa, actual_output=resposta, retrieval_context=contexto)
    metric = GEval(
        name="Diagnostico da Anomalia",
        criteria=(
            "Avalie se 'actual_output' explica a anomalia descrita em 'input' com uma causa sustentada pelos fatos "
            "de 'retrieval_context', se a natureza indicada (pontual, estrutural ou cíclica) é coerente com o "
            "histórico trimestral presente no contexto, e se diz explicitamente quando não encontrou causa clara "
            "em vez de inventar uma. Penalize causa sem evidência no contexto."
        ),
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.RETRIEVAL_CONTEXT,
        ],
        threshold=0.7,
        model=juiz,
    )
    medir(metric, tc)
