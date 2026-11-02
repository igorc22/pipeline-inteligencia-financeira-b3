"""Consolidador: junta as respostas dos agentes num relatório final.

Não é um agente com tools (create_agent): é uma chamada de saída estruturada ao LLM, seguida de
ajustes em código e da formatação em markdown.
"""
from typing import Optional

from langchain_core.messages import BaseMessage

from fluxo_financeiro.shared.types import RelatorioFinal

# Só as respostas dos workers entram no relatório: as tarefas do Supervisor e o pedido do
# usuário ficam de fora.
AGENTES_CONSOLIDADOS = ("YFinance", "Analyzer", "Investigator")

AVISO_EMERGENCIA = "> Não foi possível consolidar o relatório; seguem as respostas dos agentes."


def _secao_texto(titulo: str, texto: Optional[str]) -> list[str]:
    return [f"## {titulo}", texto.strip(), ""] if texto and texto.strip() else []


def _secao_lista(titulo: str, itens: list[str]) -> list[str]:
    return [f"## {titulo}", *(f"- {item}" for item in itens), ""] if itens else []


def formatar_relatorio(relatorio: RelatorioFinal, ticker: Optional[str]) -> str:
    """Markdown do relatório; seções vazias (ou sem diagnóstico) são omitidas."""
    titulo = f"# Relatório: {ticker}" if ticker else "# Relatório da análise"
    linhas = [
        titulo, "",
        *_secao_texto("Resumo", relatorio.resumo),
        *_secao_lista("Indicadores", relatorio.indicadores),
        *_secao_texto("Notícias e setor", relatorio.contexto),
        *_secao_texto("Diagnóstico da anomalia", relatorio.diagnostico),
        *_secao_lista("Riscos", relatorio.riscos),
        *_secao_lista("Limitações", relatorio.limitacoes),
    ]
    return "\n".join(linhas).strip() + "\n"


def relatorio_de_emergencia(messages: list[BaseMessage]) -> str:
    """Fallback sem LLM: as respostas dos agentes, na ordem em que chegaram."""
    partes = [AVISO_EMERGENCIA, ""]
    for m in messages:
        if getattr(m, "name", None) in AGENTES_CONSOLIDADOS:
            partes += [f"## {m.name}", m.text, ""]
    return "\n".join(partes).strip() + "\n"
