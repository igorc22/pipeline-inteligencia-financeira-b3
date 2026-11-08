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


class RelatorioFinal(BaseModel):
    """Resposta final da análise, montada pelo Consolidador a partir das respostas dos agentes."""
    resumo: str = Field(description="2 a 3 frases dizendo o que os dados, as notícias e o diagnóstico (se houver) mostram juntos.")
    indicadores: list[str] = Field(description="Números presentes nos insumos, um por item, no formato 'Nome: valor' (ex: 'P/L: 74,7x'). Nunca invente nem estime.")
    contexto: str = Field(description="Resumo das notícias da empresa e do contexto do setor.")
    riscos: list[str] = Field(description="Riscos apontados pelos dados, pelas notícias ou pelo diagnóstico, um por item. Só o que algum agente citou: nada genérico do setor que nenhum agente citou.")
    limitacoes: list[str] = Field(description="O que faltou ou falhou na coleta (dados ausentes, buscas sem resultado ou com erro).")
    diagnostico: Optional[str] = Field(default=None, description="Preenchido pelo sistema com o texto do Investigator. Deixe nulo.")


class ErroAgente(BaseModel):
    """Falha de um agente que o nó não resolveu localmente: o que o coordenador lê para decidir."""
    # Os mesmos valores de TRANSITORIO e PERMANENTE em shared/retry.py (escritos aqui para types.py
    # não importar as bibliotecas de rede que o retry importa).
    tipo: Literal["transitorio", "permanente"] = Field(description="Temporário: repetir pode dar certo. Permanente: repetir só gasta.")
    mensagem: str = Field(description="Tipo e texto da exceção, numa linha, com até 300 caracteres.")
    tentativas: int = Field(description="Rodadas do nó que falharam até aqui, contando as mandadas pelo coordenador.")


class MessagesState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    next_agent: str
    loop_count: Annotated[int, operator.add]
    supervisor_reasoning: str
    # Quem decidiu a última passagem do Supervisor: "guard", "llm" ou "hard_stop" (o dashboard desenha isso).
    decidido_por: str
    # Preenchido pelo nó do YFinance; se não estiver vazio, o Supervisor manda para o Investigator
    # na Etapa 4 sem consultar o LLM (guard). Ausente/vazio = o LLM decide.
    sinais_anomalia: list[SinalAnomalia]
    # Preenchido pelo Consolidador no fim do fluxo; None se o LLM dele falhou (fallback em texto).
    relatorio: Optional[RelatorioFinal]
    # Saída de cada agente num campo próprio (sobrescreve). `messages` continua com as mesmas mensagens;
    # os campos existem para decidir sem contar mensagens pelo `name`. Ausente = o agente ainda não rodou.
    # Texto final do YFinance, igual ao da mensagem: já com o aviso da reserva, os sinais e o bloco do BCB.
    dados_mercado: Optional[str]
    # Primeira passagem do Analyzer (notícias da empresa). Gravado uma vez só.
    noticias: Optional[str]
    # Passagens seguintes do Analyzer (contexto do setor); uma terceira passagem sobrescreve esta.
    contexto_setor: Optional[str]
    # Resposta do Investigator (o diagnóstico que o Consolidador copia literalmente).
    diagnostico: Optional[str]
    # Retry: cada nó repete o agente localmente antes de escalar para o coordenador. O que sobra
    # chega aqui, por agente: o último erro (None = a última rodada deu certo) e quantas rodadas do
    # nó falharam seguidas. Os dois juntam dicionários (`|`): cada nó escreve só a própria chave, e
    # limpar é escrever {agente: None} e {agente: 0} (um dicionário vazio não muda nada).
    erros: Annotated[dict[str, Optional[ErroAgente]], operator.or_]
    tentativas: Annotated[dict[str, int], operator.or_]


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
    CDI = 4389  # CDI anualizado (base 252). A série 12 é o CDI diário, ~0,05% ao dia
    IPCA_12M = 13522

class ConsultaBCBInput(BaseModel):
    indicador: IndicadorEconomico = Field(
        ...,
        description=(
            "O indicador econômico que deseja consultar: 432 para Selic meta, 433 para IPCA do mês, "
            "4389 para CDI anualizado ou 13522 para IPCA acumulado em 12 meses."
        ),
    )