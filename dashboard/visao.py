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


def passo_do_consolidador(eventos: list[tuple[str, dict]], numero: int) -> Optional[Passo]:
    """O Consolidador como último passo: a decisão de encerrar (FINISH) e o relatório que ele escreveu.

    None se a análise não chegou ao Consolidador. Ele não recebe tarefa do Supervisor: lê as
    respostas de todos os agentes, por isso a entrada fica None.
    """
    mensagens = [u.get("messages") for no, u in eventos if no == "Consolidador" and (u or {}).get("messages")]
    if not mensagens:
        return None
    finais = [u for no, u in eventos if no == "Supervisor" and (u or {}).get("next_agent") == "FINISH"]
    fim = finais[-1] if finais else {}
    return Passo(numero=numero, agente="Consolidador", rotulo="Consolidador",
                 decidido_por=fim.get("decidido_por"), raciocinio=fim.get("supervisor_reasoning"),
                 entrada=None, saida=_conteudo(mensagens[-1][-1]))


COR_APAGADA = "#9e9e9e"
COR_VOLTA = "#9e9e9e"
COR_INTERROMPIDO = "#c62828"
NO_DO_AGENTE = {"YFinance": "yfinance", "Analyzer": "analyzer", "Investigator": "investigator",
                "Consolidador": "consolidador"}


def _texto_dot(texto: str) -> str:
    """Texto seguro dentro de aspas no DOT: barra e aspas escapadas, sem quebra de linha."""
    return " ".join(texto.replace("\\", "\\\\").replace('"', '\\"').split())


def _ida(destino: str, numero: int, decidido_por: Optional[str], raciocinio: Optional[str]) -> str:
    """Seta cheia do Supervisor para o agente: número da ordem, quem decidiu e o raciocínio no tooltip."""
    atributos = []
    if decidido_por in ROTULO_DECISAO:
        cor = COR_DECISAO[decidido_por]
        atributos += [f'label="{numero} · {ROTULO_DECISAO[decidido_por]}"', f'color="{cor}"', f'fontcolor="{cor}"']
    else:
        atributos.append(f'label="{numero}"')
    if raciocinio:
        atributos.append(f'tooltip="{_texto_dot(raciocinio)}"')
    return f"  supervisor -> {destino} [{', '.join(atributos)}];"


def _no(nome: str, rotulo: str, cor: str, rodou: bool) -> str:
    if rodou:
        return f'  {nome} [label="{rotulo}", color="{cor}", fontcolor="{cor}"];'
    return (f'  {nome} [label="{rotulo}\\n(não rodou)", style="rounded,dashed", '
            f'color="{COR_APAGADA}", fontcolor="{COR_APAGADA}"];')


def dot_do_caminho(passos: list[Passo], decisao_fim: Optional[str], consolidou: bool = True) -> str:
    """DOT do grafo com o Supervisor no centro e o caminho desta análise aceso.

    Cada ida do Supervisor a um agente é uma seta cheia com o número da ordem e quem decidiu
    (o raciocínio aparece ao passar o mouse). A volta de cada agente ao Supervisor é uma seta
    tracejada. Agente que não rodou fica apagado, sem seta.

    consolidou=False (a análise falhou antes do fim): nada chega ao Consolidador; o último
    agente que rodou aponta para um nó "Interrompido".
    """
    rodaram = list(dict.fromkeys(p.agente for p in passos))  # na ordem da primeira execução
    linhas = [
        "digraph caminho {",
        "  rankdir=TB;",
        '  bgcolor="transparent";',
        "  nodesep=0.8; ranksep=0.6;",
        '  node [shape=box, style="rounded", fontname="Helvetica", fontsize=12, penwidth=2, margin="0.2,0.08"];',
        '  edge [fontname="Helvetica", fontsize=10, penwidth=1.5];',
        f'  inicio [label="Pedido", color="{COR_APAGADA}", fontcolor="{COR_APAGADA}"];',
        '  supervisor [label="Supervisor", color="#555555", fontcolor="#555555", penwidth=2.5];',
    ]
    for agente in WORKERS:
        linhas.append(_no(NO_DO_AGENTE[agente], agente, COR_AGENTE[agente], agente in rodaram))
    linhas.append("  { rank=same; yfinance; analyzer; investigator; }")
    for agente in WORKERS:
        if agente not in rodaram:  # sem seta, o graphviz o jogaria para longe dos outros
            linhas.append(f"  supervisor -> {NO_DO_AGENTE[agente]} [style=invis];")
    linhas.append(_no("consolidador", "Consolidador", COR_AGENTE["Consolidador"], consolidou))
    linhas.append("  analyzer -> consolidador [style=invis];  // põe o Consolidador abaixo dos agentes")
    linhas.append(f'  inicio -> supervisor [color="{COR_APAGADA}"];')

    for passo in passos:
        linhas.append(_ida(NO_DO_AGENTE[passo.agente], passo.numero, passo.decidido_por, passo.raciocinio))
    for agente in rodaram:
        # dir=back: a seta aponta para o Supervisor, mas o desenho mantém a hierarquia (volta reta, sem laço)
        linhas.append(f'  supervisor -> {NO_DO_AGENTE[agente]} [dir=back, style=dashed, color="{COR_VOLTA}", '
                      'arrowsize=0.7];')

    if consolidou:
        linhas.append(_ida("consolidador", len(passos) + 1, decisao_fim, None))
        linhas.append(f'  fim [label="Fim", shape=oval, color="{COR_APAGADA}", fontcolor="{COR_APAGADA}"];')
        linhas.append(f'  consolidador -> fim [color="{COR_APAGADA}"];')
    else:
        ultimo = NO_DO_AGENTE[passos[-1].agente] if passos else "supervisor"
        linhas.append(f'  interrompido [label="Interrompido", style="rounded,dashed", '
                      f'color="{COR_INTERROMPIDO}", fontcolor="{COR_INTERROMPIDO}"];')
        linhas.append(f'  {ultimo} -> interrompido [style=dashed, color="{COR_INTERROMPIDO}"];')
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
