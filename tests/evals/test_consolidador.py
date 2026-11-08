"""Evals do Consolidador, que fecha toda análise com o relatório final.

A entrada medida é montar_insumos(messages), a MESMA função que o consolidar usa para montar o texto
que vai ao LLM. Assim o juiz mede contra o que o nó recebeu de fato, não contra uma aproximação.

Três riscos, um teste para cada:
  - corromper ou inventar número ao reescrever -> Faithfulness
  - jogar conteúdo dos agentes fora            -> Summarization (a metade de cobertura)
  - responder fora do pedido do usuário        -> Answer Relevancy

Testar este nó separado dos agentes é o que localiza a falha: se o Analyzer passa e o Faithfulness daqui
reprova, o agente leu certo e o Consolidador corrompeu na reescrita.

Nada da deepeval no topo do módulo: a coleta importa este arquivo em todo pytest, fora do bloqueio de rede.
"""
import pytest

from fluxo_financeiro.agents.consolidator import montar_insumos
from tests.evals.helpers import limitar_fontes, mensagens, resposta_do_agente, sem_sumario

pytestmark = [pytest.mark.eval, pytest.mark.enable_socket]

MOTIVO_COBERTURA = (
    "Não é portão: na primeira rodada (07/11/2026, juiz gemini-3.8-flash) a nota foi 0,31 na VALE3 e 0,20 "
    "na WEGE3, e 13 de 14 vereditos 'não confirmado' eram erro do juiz (o trecho estava na entrada: fluxo de "
    "caixa, dívida, margem, China, recompra). As perguntas de cobertura saem do sumário do Yahoo (ano de "
    "fundação, sede, nome antigo), que o relatório não precisa repetir. A nota segue registrada no notas.csv. "
    "Erro do juiz (timeout, 429) não é absorvido: aparece como failed. "
    "Desde a segunda rodada da Brapi, a entrada é sem o sumário do negócio. "
    "Na rodada com os indicadores do BCB (08/11/2026), já sem o sumário, a nota foi 0,42 na VALE3 e 0,50 na "
    "WEGE3: a metade de cobertura deu 0,60 e 0,80 (ficou de fora o Beta nas duas), e quem puxou a nota foi o "
    "alinhamento, com o juiz dizendo que VaR, Alpha, dívida corrente e margem bruta não estavam na entrada "
    "(estavam, no bloco do YFinance). Continua em xfail até se mostrar estável."
)


def _relatorio(estado) -> str:
    return resposta_do_agente(estado, "Consolidador")


def test_faithfulness_consolidador(juiz, pedido, estado, medir):
    """Confere que o relatório final preserva os números e fatos dos insumos que o Consolidador recebeu.

    limitar_fontes corta só no orçamento do juiz (a produção recebe tudo); test_fixture.py confere que,
    nas fixtures geradas, o corte não tira nada. O diagnóstico do Investigator é copiado literalmente
    para o relatório, então um bloco dele cortado viraria afirmação não confirmada aqui.
    """
    from deepeval.metrics import FaithfulnessMetric
    from deepeval.test_case import LLMTestCase

    tc = LLMTestCase(
        input=pedido,
        actual_output=_relatorio(estado),
        retrieval_context=limitar_fontes(montar_insumos(mensagens(estado))),
    )
    medir(FaithfulnessMetric(threshold=0.8, model=juiz), tc)


@pytest.mark.xfail(raises=pytest.fail.Exception, strict=False, reason=MOTIVO_COBERTURA)
def test_cobertura_consolidador(juiz, estado, medir):
    """Confere que juntar as respostas dos agentes não jogou conteúdo fora.

    O input é o texto dos insumos (o "original"); a metade de cobertura gera n=5 perguntas que ele
    responde e checa se o relatório também responde. Nenhuma outra métrica pega "resumiu demais e
    perdeu o setor". A nota é a menor das duas metades; o score_breakdown do despejo diz qual puxou.

    O original vai sem o sumário do negócio (sem_sumario): as perguntas saíam dele (ano de fundação, sede,
    nome antigo), e o relatório não precisa repetir fundação e sede. O Faithfulness continua com tudo.
    """
    from deepeval.metrics import SummarizationMetric
    from deepeval.test_case import LLMTestCase

    tc = LLMTestCase(
        input="\n\n".join(sem_sumario(t) for t in limitar_fontes(montar_insumos(mensagens(estado)))),
        actual_output=_relatorio(estado),
    )
    medir(SummarizationMetric(threshold=0.7, model=juiz, n=5), tc)


def test_relevancia_consolidador(juiz, pedido, estado, medir):
    """Confere que o relatório final responde ao pedido do usuário, sem se perder ao juntar os agentes.

    Sem contexto: a métrica não olha o que entrou, só se a saída fala com o que foi pedido.
    """
    from deepeval.metrics import AnswerRelevancyMetric
    from deepeval.test_case import LLMTestCase

    tc = LLMTestCase(input=pedido, actual_output=_relatorio(estado))
    medir(AnswerRelevancyMetric(threshold=0.7, model=juiz), tc)
