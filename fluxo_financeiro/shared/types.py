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


# Subgrafo de pesquisa do Investigator (agents/pesquisa.py). Os limites de perguntas e de lacunas
# ficam só na descrição: o subgrafo corta em código, e um max_length aqui faria a saída estruturada
# falhar quando o LLM passasse do número.

class PerguntasPesquisa(BaseModel):
    """Perguntas que o subgrafo de pesquisa manda para a busca, uma busca por pergunta."""
    perguntas: list[str] = Field(
        description="Perguntas causais curtas sobre a anomalia (por que o número aconteceu), no máximo 3, cada uma pronta para virar uma busca na web."
    )


class DiagnosticoPesquisa(BaseModel):
    """Diagnóstico da anomalia, formatado em código nas 4 linhas que o e2e e o Consolidador esperam."""
    causa: str = Field(description="A causa identificada, em 1 a 2 frases, só com fatos e números dos achados e do histórico. Sem causa clara, diga que não foi identificada.")
    natureza: Literal["pontual", "estrutural", "cíclico", "indeterminado"] = Field(
        description="pontual: evento isolado. estrutural: piora contínua. cíclico: sazonal ou ligado a ciclo de preços. indeterminado: sem causa clara nos achados."
    )
    evidencias: list[str] = Field(description="Fatos e números que sustentam a causa, um por item, tirados dos achados ou do histórico. Vazia se não houver.")
    impacto: str = Field(description="O que isso muda na análise do investimento, sem recomendação de compra ou venda.")


class CriticaPesquisa(BaseModel):
    """Avaliação do diagnóstico rascunho: aprova ou pede mais buscas."""
    aprovado: bool = Field(description="true se o diagnóstico explica a anomalia com evidências dos achados.")
    lacunas: list[str] = Field(
        default_factory=list,
        description="Perguntas novas para buscar o que faltou, no máximo 2. Vazia quando aprovado.",
    )


class PesquisaFeita(BaseModel):
    """Registro do que o subgrafo de pesquisa fez: as perguntas, o que cada busca trouxe e as voltas do crítico."""
    perguntas: list[str]
    # Um por busca: {"pergunta": str, "rodada": int, "texto": str} (texto vazio = a busca não trouxe nada).
    achados: list[dict]
    voltas: int
    # O histórico trimestral que o subgrafo leu em código: entra no contexto dos evals do Investigator
    # junto com os achados (não há ToolMessage dele para o gerador da fixture ver).
    historico: str = ""


SEM_EVIDENCIAS = "nenhuma evidência encontrada nas buscas"


def formatar_diagnostico(d: DiagnosticoPesquisa, fontes: list[str]) -> str:
    """As 4 linhas-contrato do diagnóstico (Causa, Natureza, Evidências, Impacto) e as fontes no fim, quando houver."""
    # Cada evidência é uma frase do LLM, que costuma terminar em ponto: sem tirar, sairia ".;".
    evidencias = [e.strip().rstrip(".").strip() for e in d.evidencias if e.strip()]
    linhas = [
        f"- Causa identificada: {d.causa}",
        f"- Natureza do evento: {d.natureza}",
        f"- Evidências: {'; '.join(evidencias) if evidencias else SEM_EVIDENCIAS}",
        f"- Impacto no investimento: {d.impacto}",
    ]
    if fontes:
        linhas.append(f"Fontes: {', '.join(fontes)}")
    return "\n".join(linhas)


class ErroAgente(BaseModel):
    """Falha de um agente que o nó não resolveu localmente: o que o coordenador lê para decidir."""
    # Os mesmos valores de TRANSITORIO e PERMANENTE em shared/retry.py (escritos aqui para types.py
    # não importar as bibliotecas de rede que o retry importa).
    tipo: Literal["transitorio", "permanente"] = Field(description="Temporário: repetir pode dar certo. Permanente: repetir só gasta.")
    mensagem: str = Field(description="Tipo e texto da exceção, numa linha, com até 300 caracteres.")
    tentativas: int = Field(description="Rodadas do nó que falharam até aqui, contando as mandadas pelo coordenador.")


class MessagesState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    # Próximo agente a ser chamado ("YFinance", "Analyzer", "Investigator", "FINISH") ou
    # PARALELO = "Analyzer+Investigator" quando disparado pelo guard da Etapa 2.
    # O RouteDecision do LLM continua sem PARALELO (só o guard decide paralelismo).
    next_agent: str
    loop_count: Annotated[int, operator.add]
    supervisor_reasoning: str
    # Quem decidiu a última passagem do Supervisor: "guard", "llm" ou "hard_stop" (o dashboard desenha isso).
    decidido_por: str
    # Preenchido pelo nó do YFinance; se não estiver vazio, o Supervisor dispara o Analyzer e o
    # Investigator em paralelo na Etapa 2 (guard). Sem sinais, o Analyzer roda sozinho e na
    # Etapa 4 o LLM decide se investiga.
    sinais_anomalia: list[SinalAnomalia]
    # Preenchido pelo Consolidador no fim do fluxo; None se o LLM dele falhou (fallback em texto).
    relatorio: Optional[RelatorioFinal]
    # Saída de cada agente num campo próprio (sobrescreve). `messages` continua com as mesmas mensagens;
    # os campos existem para decidir sem contar mensagens pelo `name`. Ausente = o agente ainda não rodou.
    # Texto final do YFinance, igual ao da mensagem: já com o aviso da reserva, os sinais e o bloco do BCB.
    dados_mercado: Optional[str]
    # Saída da seção "## Notícias da empresa" do Analyzer (passagem única). Gravado uma vez só.
    noticias: Optional[str]
    # Saída da seção "## Contexto do setor" do Analyzer (passagem única). None se a seção faltar.
    contexto_setor: Optional[str]
    # Resposta do Investigator (o diagnóstico que o Consolidador copia literalmente).
    diagnostico: Optional[str]
    # O que o subgrafo de pesquisa do Investigator fez (perguntas, achados, voltas do crítico, histórico).
    # Só o ramo do Investigator escreve aqui, então o paralelo não disputa a chave.
    pesquisa: Optional[PesquisaFeita]
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