"""Transforma os eventos do app.stream e o state final no que o dashboard mostra.

Funções puras, sem Streamlit: o app.py só desenha o que sai daqui. O dashboard reorganiza o
que está no state; nunca calcula nem reformata números.
"""
from dataclasses import dataclass
from typing import Optional

WORKERS = ("YFinance", "Analyzer", "Investigator")

ROTULO_DECISAO = {"guard": "guard", "llm": "LLM", "hard_stop": "hard stop"}
COR_DECISAO = {"guard": "#2e7d32", "llm": "#1565c0", "hard_stop": "#c62828"}
COR_AGENTE = {"YFinance": "#e0a030", "Analyzer": "#3fb37f", "Investigator": "#e05555", "Consolidador": "#9b7bff"}
ROTULO_ANALYZER = {1: "Analyzer (empresa)", 2: "Analyzer (setor)"}
# O st.metric corta com reticências o que não cabe no quadro: acima disso, o indicador vai para a lista
MAX_NOME_QUADRO = 28
MAX_VALOR_QUADRO = 18


@dataclass
class Passo:
    """Uma execução de worker: o que ele recebeu do Supervisor e o que devolveu."""
    numero: int
    agente: str
    rotulo: str
    decidido_por: Optional[str]
    raciocinio: Optional[str]
    entrada: Optional[str]
    saida: str


def separar_indicador(texto: str) -> tuple[str, Optional[str]]:
    """'P/L: 5.0x' → ('P/L', '5.0x'). Separa no primeiro ': '; sem ele, o valor é None."""
    nome, separador, valor = texto.partition(": ")
    return (nome, valor) if separador else (texto, None)


def dividir_indicadores(indicadores: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """(quadros, linhas): 'Nome: valor' curtos viram quadro; longos ou sem valor viram linha inteira."""
    quadros: list[tuple[str, str]] = []
    linhas: list[str] = []
    for texto in indicadores:
        nome, valor = separar_indicador(texto)
        if valor is not None and len(nome) <= MAX_NOME_QUADRO and len(valor) <= MAX_VALOR_QUADRO:
            quadros.append((nome, valor))
        else:
            linhas.append(texto)
    return quadros, linhas


def escapar_markdown(texto: str) -> str:
    """Escapa o $: o markdown do Streamlit lê '$...$' como fórmula e estraga 'R$ 3,2 bi contra R$ 5,0 bi'."""
    return texto.replace("$", "\\$")


def _conteudo(mensagem) -> str:
    conteudo = mensagem.content
    return conteudo if isinstance(conteudo, str) else str(mensagem.text)


def montar_passos(eventos: list[tuple[str, dict]]) -> list[Passo]:
    """Um Passo por evento de worker, com a decisão e a tarefa do Supervisor que veio logo antes."""
    passos: list[Passo] = []
    supervisor: Optional[dict] = None
    passagens_analyzer = 0
    for no, update in eventos:
        update = update or {}
        if no == "Supervisor":
            supervisor = update
            continue
        if no not in WORKERS:
            continue
        rotulo = no
        if no == "Analyzer":
            passagens_analyzer += 1
            rotulo = ROTULO_ANALYZER.get(passagens_analyzer, f"Analyzer ({passagens_analyzer})")
        tarefa = (supervisor or {}).get("messages") or []
        passos.append(Passo(
            numero=len(passos) + 1,
            agente=no,
            rotulo=rotulo,
            decidido_por=(supervisor or {}).get("decidido_por"),
            raciocinio=(supervisor or {}).get("supervisor_reasoning"),
            entrada=_conteudo(tarefa[-1]) if tarefa else None,
            saida=_conteudo(update["messages"][-1]) if update.get("messages") else "",
        ))
        supervisor = None  # a decisão já foi usada; o próximo worker precisa de outra
    return passos


def decisao_do_fim(eventos: list[tuple[str, dict]]) -> Optional[str]:
    """Quem decidiu o FINISH (a última passagem do Supervisor que mandou encerrar)."""
    finais = [u for no, u in eventos if no == "Supervisor" and (u or {}).get("next_agent") == "FINISH"]
    return finais[-1].get("decidido_por") if finais else None


def parou_no_hard_stop(eventos: list[tuple[str, dict]]) -> bool:
    return decisao_do_fim(eventos) == "hard_stop"


def _aresta(origem: str, destino: str, decidido_por: Optional[str]) -> str:
    if decidido_por not in ROTULO_DECISAO:
        return f"  {origem} -> {destino};"
    cor = COR_DECISAO[decidido_por]
    return (f'  {origem} -> {destino} [label="{ROTULO_DECISAO[decidido_por]}", '
            f'color="{cor}", fontcolor="{cor}"];')


def _no(nome: str, rotulo: str, cor: str) -> str:
    return f'  {nome} [label="{rotulo}", color="{cor}", fontcolor="{cor}"];'


def dot_do_caminho(passos: list[Passo], decisao_fim: Optional[str], consolidou: bool = True) -> str:
    """DOT do caminho percorrido, da esquerda para a direita, com quem decidiu cada passo.

    consolidou=False (a análise falhou antes do fim): o caminho termina num nó "Interrompido",
    e o Investigator tracejado não aparece (não dá para dizer que ele "não rodou" por escolha).
    """
    linhas = [
        "digraph caminho {",
        "  rankdir=LR;",
        '  bgcolor="transparent";',
        '  node [shape=box, style="rounded", fontname="Helvetica", fontsize=12, penwidth=2];',
        '  edge [fontname="Helvetica", fontsize=10, penwidth=1.5];',
        '  inicio [label="Pedido", color="#888888", fontcolor="#888888"];',
    ]
    anterior = "inicio"
    for passo in passos:
        nome = f"p{passo.numero}"
        linhas.append(_no(nome, passo.rotulo, COR_AGENTE[passo.agente]))
        linhas.append(_aresta(anterior, nome, passo.decidido_por))
        anterior = nome
    if not consolidou:
        linhas.append('  interrompido [label="Interrompido", style="rounded,dashed", '
                      'color="#c62828", fontcolor="#c62828"];')
        linhas.append(f'  {anterior} -> interrompido [style=dashed, color="#c62828"];')
        linhas.append("}")
        return "\n".join(linhas)
    linhas.append(_no("consolidador", "Consolidador", COR_AGENTE["Consolidador"]))
    linhas.append(_aresta(anterior, "consolidador", decisao_fim))
    if not any(p.agente == "Investigator" for p in passos):
        linhas.append('  investigator [label="Investigator\\n(não rodou)", style="rounded,dashed", '
                      'color="#777777", fontcolor="#777777"];')
        linhas.append(f'  {anterior} -> investigator [style=dashed, color="#777777", arrowhead=none];')
    linhas.append("}")
    return "\n".join(linhas)


def _jsonavel(valor):
    return valor.model_dump() if hasattr(valor, "model_dump") else valor


def state_para_json(state: dict) -> dict:
    """State final como dict serializável: mensagens como {tipo, name, conteudo}; modelos como dict."""
    resultado = {}
    for chave, valor in state.items():
        if chave == "messages":
            resultado[chave] = [
                {"tipo": type(m).__name__, "name": getattr(m, "name", None), "conteudo": _conteudo(m)}
                for m in valor
            ]
        elif isinstance(valor, list):
            resultado[chave] = [_jsonavel(v) for v in valor]
        else:
            resultado[chave] = _jsonavel(valor)
    return resultado
