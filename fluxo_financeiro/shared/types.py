import operator
from typing import Annotated, Literal, Optional
from enum import IntEnum
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class SinalAnomalia(BaseModel):
    """Sinal de anomalia calculado em código (sem LLM) a partir dos números da empresa."""
    tipo: Literal["queda_lucro", "prejuizo", "piotroski_fraco"]
    descricao: str = Field(description="Frase com os números, pronta para virar tarefa do Investigator.")


class MessagesState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    next_agent: str
    loop_count: Annotated[int, operator.add]
    supervisor_reasoning: str
    # Preenchido pelo nó do YFinance; se não estiver vazio, o Supervisor manda para o Investigator
    # na Etapa 4 sem consultar o LLM (guard). Ausente/vazio = o LLM decide.
    sinais_anomalia: list[SinalAnomalia]


class RouteDecision(BaseModel):
    reasoning: str = Field(
        description="Em 1-2 frases, explique o que você observou no histórico e por que está tomando esta decisão de roteamento."
    )
    next_agent: Literal["YFinance", "Analyzer","Investigator", "FINISH"] = Field(
        description="""
        Decida o próximo passo do fluxo:
        - 'YFinance': Se faltam dados financeiros ou se o Analyzer pedir mais informações para concluir a tarefa.
        - 'Analyzer': Se os dados foram coletados com sucesso e estão prontos para serem analisados.
        - 'Investigator': Se há anomalia financeira clara que precisa de diagnóstico causal (queda abrupta de lucro, impairment suspeito, dívida inexplicável).
        - 'FINISH': Se o usuário já tem a resposta final e completa, ou se os agentes não conseguem encontrar o dado após tentarem.
        """
    )
    task_for_agent: Optional[str] = Field(
        default=None,
        description="Instrução específica para o próximo agente. Obrigatório quando next_agent é 'YFinance' ou 'Analyzer'. Deve ser null apenas para 'FINISH'. Exemplo: 'Busque informações sobre o setor de automação industrial da WEG (WEGE3).'",
    )

class IndicadorEconomico(IntEnum):
    SELIC_META = 432
    IPCA = 433
    CDI = 12

class ConsultaBCBInput(BaseModel):
    indicador: IndicadorEconomico = Field(
        ..., 
        description="O indicador econômico que deseja consultar: 432 para Selic, 433 para IPCA ou 12 para CDI."
    )