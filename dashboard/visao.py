"""Transforma os eventos do app.stream e o state final no que o dashboard mostra.

Funções puras, sem Streamlit: o app.py só desenha o que sai daqui. O dashboard reorganiza o
que está no state; nunca calcula nem reformata números.
"""
from dataclasses import dataclass
from typing import Collection, Optional

WORKERS = ("YFinance", "Analyzer", "Investigator")
PARALELO = "Analyzer+Investigator"
RAMOS_PARALELO = ("Analyzer", "Investigator")

ROTULO_DECISAO = {"guard": "guard", "llm": "LLM", "hard_stop": "hard stop"}
COR_DECISAO = {"guard": "#2e7d32", "llm": "#1565c0", "hard_stop": "#c62828"}
COR_AGENTE = {"YFinance": "#e0a030", "Analyzer": "#3fb37f", "Investigator": "#e05555", "Consolidador": "#9b7bff"}
FUNDO_ATIVO = {"YFinance": "#fff8e1", "Analyzer": "#e8f5e9", "Investigator": "#ffebee", "Consolidador": "#f3e5f5"}
FUNDO_CONCLUIDO = {"YFinance": "#fffdf7", "Analyzer": "#f6fbf8", "Investigator": "#fff8f8", "Consolidador": "#faf7ff"}
ROTULO_ANALYZER = {1: "Analyzer (empresa)", 2: "Analyzer (setor)"}
DESCRICAO_CONCLUIDA = {
    "YFinance": "coletou os dados de mercado",
    "Analyzer (empresa)": "buscou as notícias da empresa",
    "Analyzer (setor)": "buscou o contexto do setor",
    "Investigator": "investigou a anomalia",
    "Consolidador": "montou o relatório",
}
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
    if not isinstance(texto, str):
        texto = str(texto) if texto is not None else ""
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
    if not isinstance(texto, str):
        texto = str(texto) if texto is not None else ""
    return texto.replace("$", "\\$")


def _conteudo(mensagem) -> str:
    if mensagem is None:
        return ""
    if isinstance(mensagem, str):
        return mensagem
    if isinstance(mensagem, dict):
        if "content" in mensagem:
            conteudo = mensagem["content"]
            return conteudo if isinstance(conteudo, str) else str(conteudo if conteudo is not None else "")
        return str(mensagem)
    conteudo = getattr(mensagem, "content", None)
    if isinstance(conteudo, str):
        return conteudo
    if hasattr(mensagem, "text"):
        return str(mensagem.text)
    return str(conteudo) if conteudo is not None else str(mensagem)


def _dict(valor) -> dict:
    return valor if isinstance(valor, dict) else {}


def montar_passos(eventos: list[tuple[str, dict]]) -> list[Passo]:
    """Um Passo por evento de worker, com a decisão e a tarefa do Supervisor que veio logo antes."""
    passos: list[Passo] = []
    supervisor: Optional[dict] = None
    passagens_analyzer = 0
    passo_numero = 0
    ramos_pendentes: set[str] = set()

    for no, update in eventos:
        dados = _dict(update)
        if no == "Supervisor":
            supervisor = dados
            proximo = supervisor.get("next_agent")
            if proximo == PARALELO:
                passo_numero += 1
                ramos_pendentes = set(WORKERS) & set(RAMOS_PARALELO)
            elif proximo != "FINISH":
                passo_numero += 1
                ramos_pendentes = {proximo} if proximo in WORKERS else set()
            else:
                ramos_pendentes = set()
            continue
        if no not in WORKERS:
            continue
        rotulo = no
        if no == "Analyzer":
            passagens_analyzer += 1
            rotulo = ROTULO_ANALYZER.get(passagens_analyzer, f"Analyzer ({passagens_analyzer})")
        sup = supervisor or {}
        tarefas = sup.get("messages") or []

        if sup.get("next_agent") == PARALELO and isinstance(tarefas, list) and len(tarefas) >= 2:
            if no == "Analyzer":
                tarefa_msg = next((m for m in tarefas if "## Notícias da empresa" in _conteudo(m) or "notícias" in _conteudo(m).lower()), tarefas[0])
            else:
                tarefa_msg = next((m for m in tarefas if "Investigue" in _conteudo(m) or "investig" in _conteudo(m).lower()), tarefas[1])
            entrada = _conteudo(tarefa_msg)
        else:
            entrada = _conteudo(tarefas[-1]) if isinstance(tarefas, list) and tarefas else (_conteudo(tarefas) if tarefas else None)

        msgs_saida = dados.get("messages")
        if isinstance(msgs_saida, list) and msgs_saida:
            saida = _conteudo(msgs_saida[-1])
        elif msgs_saida is not None:
            saida = _conteudo(msgs_saida)
        elif not dados and update:
            saida = _conteudo(update)
        else:
            saida = ""

        numero_atual = passo_numero if passo_numero > 0 else (len(passos) + 1)
        passos.append(Passo(
            numero=numero_atual,
            agente=no,
            rotulo=rotulo,
            decidido_por=sup.get("decidido_por"),
            raciocinio=sup.get("supervisor_reasoning"),
            entrada=entrada,
            saida=saida,
        ))
        ramos_pendentes.discard(no)
        if not ramos_pendentes:
            supervisor = None
    return passos


def decisao_do_fim(eventos: list[tuple[str, dict]]) -> Optional[str]:
    """Quem decidiu o FINISH (a última passagem do Supervisor que mandou encerrar)."""
    finais = [_dict(u) for no, u in eventos if no == "Supervisor" and _dict(u).get("next_agent") == "FINISH"]
    return finais[-1].get("decidido_por") if finais else None


def raciocinio_do_fim(eventos: list[tuple[str, dict]]) -> Optional[str]:
    """Raciocínio da decisão do FINISH (a última passagem do Supervisor que mandou encerrar)."""
    finais = [_dict(u) for no, u in eventos if no == "Supervisor" and _dict(u).get("next_agent") == "FINISH"]
    return finais[-1].get("supervisor_reasoning") if finais else None


def parou_no_hard_stop(eventos: list[tuple[str, dict]]) -> bool:
    return decisao_do_fim(eventos) == "hard_stop"


def passo_do_consolidador(eventos: list[tuple[str, dict]], numero: int) -> Optional[Passo]:
    """O Consolidador como último passo: a decisão de encerrar (FINISH) e o relatório que ele escreveu.

    None se a análise não chegou ao Consolidador. Ele não recebe tarefa do Supervisor: lê as
    respostas de todos os agentes, por isso a entrada fica None.
    """
    mensagens = []
    for no, u in eventos:
        if no == "Consolidador":
            dados = _dict(u)
            msgs = dados.get("messages")
            if isinstance(msgs, list) and msgs:
                mensagens.append(msgs[-1])
            elif msgs is not None:
                mensagens.append(msgs)
            elif not dados and u:
                mensagens.append(u)
    if not mensagens:
        return None
    return Passo(
        numero=numero,
        agente="Consolidador",
        rotulo="Consolidador",
        decidido_por=decisao_do_fim(eventos),
        raciocinio=raciocinio_do_fim(eventos),
        entrada=None,
        saida=_conteudo(mensagens[-1]),
    )


def rotulo_agente_em_execucao(proximo: Optional[str], passagens_analyzer: int = 0) -> str:
    """Rótulo do agente que começa a rodar agora a partir da decisão do Supervisor."""
    if not proximo:
        return ""
    if not isinstance(proximo, str):
        proximo = str(proximo)
    if proximo == "FINISH":
        return "Consolidador"
    if proximo == "Analyzer":
        passo_atual = passagens_analyzer + 1
        return ROTULO_ANALYZER.get(passo_atual, f"Analyzer ({passo_atual})")
    if proximo == PARALELO:
        return "Analyzer e Investigator"
    return proximo


def status_execucao(ticker: str, rotulo: Optional[str] = None) -> str:
    """Texto do status exibido enquanto o agente está executando."""
    ticker_str = str(ticker) if ticker is not None else ""
    return f"Analisando {ticker_str}: {rotulo}..." if rotulo else f"Analisando {ticker_str}..."


def resumo_em_progresso(eventos: list[tuple[str, dict]]) -> str:
    """Markdown com a linha do tempo ao vivo: passos concluídos e o agente rodando agora com o motivo."""
    passos = montar_passos(eventos)
    consolidou = any(no == "Consolidador" for no, _ in eventos)
    linhas: list[str] = ["**Passos da análise**"]

    for p in passos:
        decisao = ROTULO_DECISAO.get(p.decidido_por or "")
        via = f" *(via {decisao})*" if decisao else ""
        acao = DESCRICAO_CONCLUIDA.get(p.rotulo, "concluiu a etapa")
        linhas.append(f"- :material/check_circle: **{p.numero} · {p.rotulo}**{via} — {acao}")

    proximo_num = max((p.numero for p in passos), default=0) + 1
    if consolidou:
        decisao = ROTULO_DECISAO.get(decisao_do_fim(eventos) or "")
        via = f" *(via {decisao})*" if decisao else ""
        linhas.append(f"- :material/check_circle: **{proximo_num} · Consolidador**{via} — montou o relatório")
    elif eventos and eventos[-1][0] == "Supervisor":
        sup = _dict(eventos[-1][1])
        passagens_analyzer = sum(1 for p in passos if p.agente == "Analyzer")
        rotulo_ativo = rotulo_agente_em_execucao(sup.get("next_agent"), passagens_analyzer)
        if rotulo_ativo:
            decisao = ROTULO_DECISAO.get(sup.get("decidido_por") or "")
            via = f" *(decidido por {decisao})*" if decisao else ""
            linhas.append(f"- :material/pending: **{proximo_num} · {rotulo_ativo}** — rodando agora{via}")
            raciocinio = sup.get("supervisor_reasoning")
            if raciocinio:
                linhas.append(f"  > _{escapar_markdown(str(raciocinio))}_")
    elif not passos:
        linhas.append("_Iniciando o Supervisor..._")

    return "\n".join(linhas)


COR_APAGADA = "#9e9e9e"
COR_VOLTA = "#9e9e9e"
COR_INTERROMPIDO = "#c62828"
NO_DO_AGENTE = {"YFinance": "yfinance", "Analyzer": "analyzer", "Investigator": "investigator",
                "Consolidador": "consolidador"}


def _texto_dot(texto: str) -> str:
    """Texto seguro dentro de aspas no DOT: barra e aspas escapadas, sem quebra de linha."""
    if not isinstance(texto, str):
        texto = str(texto) if texto is not None else ""
    return " ".join(texto.replace("\\", "\\\\").replace('"', '\\"').split())


def _ida(destino: str, numero: int, decidido_por: Optional[str], raciocinio: Optional[str],
         ativo: bool = False) -> str:
    """Seta cheia do Supervisor para o agente: número da ordem, quem decidiu e o raciocínio no tooltip."""
    atributos = []
    if decidido_por in ROTULO_DECISAO:
        cor = COR_DECISAO[decidido_por]
        atributos += [f'label="{numero} · {ROTULO_DECISAO[decidido_por]}"', f'color="{cor}"', f'fontcolor="{cor}"']
    else:
        atributos.append(f'label="{numero}"')
    if raciocinio:
        atributos.append(f'tooltip="{_texto_dot(raciocinio)}"')
    if ativo:
        atributos.append('penwidth=2.5')
        atributos.append('style="bold"')
    return f"  supervisor -> {destino} [{', '.join(atributos)}];"


def _no(nome: str, rotulo: str, cor: str, rodou: bool, ativo: bool = False) -> str:
    if ativo:
        fundo = FUNDO_ATIVO.get(rotulo, "#fffde7")
        return (f'  {nome} [label="{rotulo}\\n(rodando agora)", color="{cor}", fontcolor="{cor}", '
                f'fillcolor="{fundo}", penwidth=3, style="rounded,filled,bold"];')
    if rodou:
        fundo = FUNDO_CONCLUIDO.get(rotulo, "#fafafa")
        return f'  {nome} [label="{rotulo}", color="{cor}", fontcolor="{cor}", fillcolor="{fundo}", style="rounded,filled"];'
    return (f'  {nome} [label="{rotulo}\\n(não rodou)", style="rounded,dashed", '
            f'color="{COR_APAGADA}", fontcolor="{COR_APAGADA}"];')


def dot_do_caminho(
    passos: list[Passo],
    decisao_fim: Optional[str],
    consolidou: bool = True,
    em_execucao: Optional[str | Collection[str]] = None,
    decisao_ativa: Optional[str] = None,
    raciocinio_ativo: Optional[str] = None,
    em_progresso: bool = False,
    raciocinio_fim: Optional[str] = None,
    numero_ativo: Optional[int] = None,
) -> str:
    """DOT do grafo com o Supervisor no centro e o caminho desta análise aceso.

    Cada ida do Supervisor a um agente é uma seta cheia com o número da ordem e quem decidiu
    (o raciocínio aparece ao passar o mouse). A volta de cada agente ao Supervisor é uma seta
    tracejada. Agente que não rodou fica apagado, sem seta.

    Durante a execução (em_progresso=True), o nó que está rodando ganha destaque ('(rodando agora)')
    e a seta do Supervisor para ele é realçada em negrito e com maior espessura.

    consolidou=False (a análise falhou antes do fim): nada chega ao Consolidador; o último
    agente que rodou aponta para um nó "Interrompido".
    """
    if isinstance(em_execucao, str):
        ativos = {em_execucao}
    elif em_execucao:
        ativos = set(em_execucao)
    else:
        ativos = set()

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
        linhas.append(_no(
            NO_DO_AGENTE[agente],
            agente,
            COR_AGENTE[agente],
            rodou=agente in rodaram,
            ativo=(em_progresso and agente in ativos),
        ))
    linhas.append("  { rank=same; yfinance; analyzer; investigator; }")
    for agente in WORKERS:
        if agente not in rodaram and not (em_progresso and agente in ativos):  # sem seta, o graphviz o jogaria para longe dos outros
            linhas.append(f"  supervisor -> {NO_DO_AGENTE[agente]} [style=invis];")
    linhas.append(_no(
        "consolidador",
        "Consolidador",
        COR_AGENTE["Consolidador"],
        rodou=consolidou,
        ativo=(em_progresso and "Consolidador" in ativos),
    ))
    linhas.append("  analyzer -> consolidador [style=invis];  // põe o Consolidador abaixo dos agentes")
    linhas.append(f'  inicio -> supervisor [color="{COR_APAGADA}"];')

    for passo in passos:
        destino = NO_DO_AGENTE.get(passo.agente)
        if destino:
            linhas.append(_ida(destino, passo.numero, passo.decidido_por, passo.raciocinio))
    for agente in rodaram:
        destino = NO_DO_AGENTE.get(agente)
        if destino:
            # dir=back: a seta aponta para o Supervisor, mas o desenho mantém a hierarquia (volta reta, sem laço)
            linhas.append(f'  supervisor -> {destino} [dir=back, style=dashed, color="{COR_VOLTA}", '
                          'arrowsize=0.7];')

    proximo_numero = numero_ativo if numero_ativo is not None else (max((p.numero for p in passos), default=0) + 1)
    if em_progresso:
        for ag in WORKERS:
            if ag in ativos:
                destino = NO_DO_AGENTE.get(ag)
                if destino:
                    linhas.append(_ida(destino, proximo_numero, decisao_ativa, raciocinio_ativo, ativo=True))
        if "Consolidador" in ativos:
            linhas.append(_ida("consolidador", proximo_numero, decisao_ativa, raciocinio_ativo, ativo=True))
    elif consolidou:
        num_consolidador = max((p.numero for p in passos), default=0) + 1
        linhas.append(_ida("consolidador", num_consolidador, decisao_fim, raciocinio_fim))
        linhas.append(f'  fim [label="Fim", shape=oval, color="{COR_APAGADA}", fontcolor="{COR_APAGADA}"];')
        linhas.append(f'  consolidador -> fim [color="{COR_APAGADA}"];')
    else:
        ultimo = NO_DO_AGENTE.get(passos[-1].agente, "supervisor") if passos else "supervisor"
        linhas.append(f'  interrompido [label="Interrompido", style="rounded,dashed", '
                      f'color="{COR_INTERROMPIDO}", fontcolor="{COR_INTERROMPIDO}"];')
        linhas.append(f'  {ultimo} -> interrompido [style=dashed, color="{COR_INTERROMPIDO}"];')
    linhas.append("}")
    return "\n".join(linhas)


def dot_do_caminho_em_progresso(eventos: list[tuple[str, dict]]) -> str:
    """DOT do grafo durante a execução, destacando o nó que está rodando e a seta ativa."""
    if any(no == "Consolidador" for no, _ in eventos):
        return dot_do_caminho(
            montar_passos(eventos),
            decisao_do_fim(eventos),
            consolidou=True,
            raciocinio_fim=raciocinio_do_fim(eventos),
        )

    passos = montar_passos(eventos)
    agentes_ativos: set[str] = set()
    decisao_ativa: Optional[str] = None
    raciocinio_ativo: Optional[str] = None
    numero_ativo: Optional[int] = None

    for i in range(len(eventos) - 1, -1, -1):
        no, u = eventos[i]
        if no == "Supervisor":
            sup = _dict(u)
            proximo = sup.get("next_agent")
            decisao_ativa = sup.get("decidido_por")
            raciocinio_ativo = sup.get("supervisor_reasoning")
            if proximo == "FINISH":
                agentes_ativos = {"Consolidador"}
                numero_ativo = max((p.numero for p in passos), default=0) + 1
            elif proximo == PARALELO:
                completados = {n for n, _ in eventos[i + 1:] if n in RAMOS_PARALELO}
                agentes_ativos = set(RAMOS_PARALELO) - completados
                numero_ativo = sum(1 for n, d in eventos[:i + 1] if n == "Supervisor" and _dict(d).get("next_agent") != "FINISH")
            elif proximo in WORKERS:
                agentes_ativos = {proximo}
                numero_ativo = sum(1 for n, d in eventos[:i + 1] if n == "Supervisor" and _dict(d).get("next_agent") != "FINISH")
            break

    return dot_do_caminho(
        passos=passos,
        decisao_fim=None,
        consolidou=False,
        em_execucao=agentes_ativos,
        decisao_ativa=decisao_ativa,
        raciocinio_ativo=raciocinio_ativo,
        em_progresso=True,
        numero_ativo=numero_ativo,
    )


dot_em_progresso = dot_do_caminho_em_progresso


def _jsonavel(valor):
    # Dicionários do state (erros, tentativas) guardam modelos dentro: converte os valores também.
    if isinstance(valor, dict):
        return {k: _jsonavel(v) for k, v in valor.items()}
    return valor.model_dump() if hasattr(valor, "model_dump") else valor


def state_para_json(state: dict) -> dict:
    """State final como dict serializável: mensagens como {tipo, name, conteudo}; modelos como dict."""
    if not isinstance(state, dict):
        return {}
    resultado = {}
    for chave, valor in state.items():
        if chave == "messages":
            if isinstance(valor, list):
                resultado[chave] = [
                    {"tipo": type(m).__name__, "name": getattr(m, "name", None), "conteudo": _conteudo(m)}
                    for m in valor
                ]
            else:
                resultado[chave] = _jsonavel(valor)
        elif isinstance(valor, list):
            resultado[chave] = [_jsonavel(v) for v in valor]
        else:
            resultado[chave] = _jsonavel(valor)
    return resultado
