"""Saída do servidor A2A: as partes do artefato e o contexto que liga a execução ao trace do cliente."""
from a2a.helpers import new_data_part, new_text_part
from a2a.types import Part
from langsmith.run_trees import RunTree

from fluxo_financeiro.shared.utils import logger

NOME_ARTEFATO = "relatorio"

# Cabeçalhos que carregam o trace do cliente. Só os nomes vão ao log: os valores podem trazer credencial.
CABECALHOS_DE_TRACE = ("langsmith-trace", "baggage", "traceparent", "tracestate")
PREFIXO_LITELLM = "x-litellm-"


def montar_partes(ticker: str, estado: dict) -> list[Part]:
    """Parte de texto (markdown do Consolidador) e, se houver, a parte de dados com o relatório em JSON."""
    texto = new_text_part(estado["messages"][-1].content, media_type="text/markdown")
    partes = [texto]
    relatorio = estado.get("relatorio")
    # Sem relatório estruturado (o LLM do Consolidador falhou), o cliente fica só com o markdown.
    if relatorio is not None:
        partes.append(new_data_part({"ticker": ticker, "relatorio": relatorio.model_dump()},
                                    media_type="application/json"))
    return partes


def contexto_de_trace(cabecalhos: dict[str, str]) -> dict:
    """Argumentos de tracing_context: o pai do trace do cliente (se houver) e os metadados da execução."""
    contexto: dict = {}
    if "langsmith-trace" in cabecalhos:
        # O pai leva só o que o LangSmith usa para ligar as execuções, não o cabeçalho inteiro.
        pai = {"langsmith-trace": cabecalhos["langsmith-trace"]}
        if "baggage" in cabecalhos:
            pai["baggage"] = cabecalhos["baggage"]
        # O cabeçalho vem de fora: um valor malformado faria o tracing_context levantar no meio da análise.
        # O LangSmith recusa alguns pais devolvendo None, sem exceção: esse caso também sai do contexto.
        try:
            pai_valido = RunTree.from_headers(pai) is not None
        except Exception:
            pai_valido = False
        if pai_valido:
            contexto["parent"] = pai
        else:
            logger.warning("[a2a] cabeçalho langsmith-trace inválido: trace do chamador ignorado")

    metadados = {"entrada": "a2a"}
    if "x-litellm-trace-id" in cabecalhos:
        metadados["litellm_trace_id"] = cabecalhos["x-litellm-trace-id"]
    if "x-litellm-agent-id" in cabecalhos:
        metadados["litellm_agent_id"] = cabecalhos["x-litellm-agent-id"]
    contexto["metadata"] = metadados
    return contexto


def nomes_de_trace(cabecalhos: dict[str, str]) -> list[str]:
    """Nomes, em ordem, dos cabeçalhos de trace recebidos (para o log, sem os valores)."""
    return sorted(
        nome for nome in cabecalhos
        if nome in CABECALHOS_DE_TRACE or nome.startswith(PREFIXO_LITELLM)
    )
