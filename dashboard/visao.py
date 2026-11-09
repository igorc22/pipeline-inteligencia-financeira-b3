"""Transforma os eventos do app.stream e o state final no que o dashboard mostra.

Funções puras, sem Streamlit: o app.py só desenha o que sai daqui. O dashboard reorganiza o
que está no state; nunca calcula nem reformata números.
"""
from dataclasses import dataclass
import re
from typing import Collection, Optional

from fluxo_financeiro.shared.prompts import TAG_CONTEUDO_EXTERNO
from fluxo_financeiro.shared.retry import MAX_TENTATIVAS
from fluxo_financeiro.shared.types import ErroAgente, PesquisaFeita

WORKERS = ("YFinance", "Analyzer", "Investigator")
PARALELO = "Analyzer+Investigator"
RAMOS_PARALELO = ("Analyzer", "Investigator")

ROTULO_DECISAO = {"guard": "guard", "llm": "LLM", "hard_stop": "hard stop"}
COR_DECISAO = {"guard": "#2e7d32", "llm": "#1565c0", "hard_stop": "#c62828"}
COR_AGENTE = {"YFinance": "#e0a030", "Analyzer": "#3fb37f", "Investigator": "#e05555", "Consolidador": "#9b7bff"}
FUNDO_ATIVO = {"YFinance": "#fff8e1", "Analyzer": "#e8f5e9", "Investigator": "#ffebee", "Consolidador": "#f3e5f5"}
FUNDO_CONCLUIDO = {"YFinance": "#fffdf7", "Analyzer": "#f6fbf8", "Investigator": "#fff8f8", "Consolidador": "#faf7ff"}
DESCRICAO_CONCLUIDA = {
    "YFinance": "coletou os dados de mercado",
    "Analyzer": "buscou as notícias da empresa e o contexto do setor",
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
    pesquisa: Optional[PesquisaFeita] = None
    erro: Optional[ErroAgente] = None
    tentativa: int = 1
    reenvio: bool = False
    desistiu: bool = False


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


def _extrair_erro(agente: str, dados: dict, saida: str, tentativa_num: int) -> Optional[ErroAgente]:
    """Extrai o ErroAgente do update do nó (ou reconstrói a partir do prefixo 'Erro: <agente> falhou')."""
    erros_dict = _dict(dados.get("erros"))
    bruto = erros_dict.get(agente)
    if isinstance(bruto, ErroAgente):
        return bruto
    if isinstance(bruto, dict):
        try:
            return ErroAgente(**bruto)
        except Exception:
            pass
    prefixo = f"Erro: {agente} falhou depois de "
    if isinstance(saida, str) and saida.startswith(prefixo):
        tipo = "permanente" if "(permanente)" in saida else "transitorio"
        return ErroAgente(tipo=tipo, mensagem=saida, tentativas=tentativa_num)
    return None


def _extrair_pesquisa(dados: dict) -> Optional[PesquisaFeita]:
    """Extrai o PesquisaFeita gravado pelo subgrafo do Investigator."""
    bruto = dados.get("pesquisa")
    if isinstance(bruto, PesquisaFeita):
        return bruto
    if isinstance(bruto, dict):
        try:
            return PesquisaFeita(**bruto)
        except Exception:
            return None
    return None


def _extrair_tarefas_paralelo(tarefas: list) -> tuple[str, str]:
    """Separa a tarefa do Analyzer e a do Investigator na lista de mensagens do paralelo."""
    t_ana = next(
        (m for m in tarefas if "## Notícias da empresa" in _conteudo(m) or "notícias" in _conteudo(m).lower()),
        tarefas[0],
    )
    t_inv = next(
        (m for m in tarefas if "Investigue" in _conteudo(m) or "investig" in _conteudo(m).lower()),
        tarefas[1],
    )
    return _conteudo(t_ana), _conteudo(t_inv)


def montar_passos(eventos: list[tuple[str, dict]]) -> list[Passo]:
    """Um Passo por evento de worker, com a decisão e a tarefa do Supervisor que veio logo antes."""
    passos: list[Passo] = []
    supervisor: Optional[dict] = None
    passagens_analyzer = 0
    passo_numero = 0
    ramos_pendentes: set[str] = set()
    ultima_tarefa: dict[str, str] = {}
    falhas_seguidas: dict[str, int] = {}
    indice_evento_passo: list[int] = []

    for idx_ev, (no, update) in enumerate(eventos):
        dados = _dict(update)
        if no == "Supervisor":
            supervisor = dados
            proximo = supervisor.get("next_agent")
            tarefas = supervisor.get("messages") or []
            if proximo == PARALELO:
                passo_numero += 1
                ramos_pendentes = set(WORKERS) & set(RAMOS_PARALELO)
                if isinstance(tarefas, list) and len(tarefas) >= 2:
                    t_ana, t_inv = _extrair_tarefas_paralelo(tarefas)
                    if t_ana:
                        ultima_tarefa["Analyzer"] = t_ana
                    if t_inv:
                        ultima_tarefa["Investigator"] = t_inv
            elif proximo in WORKERS:
                passo_numero += 1
                ramos_pendentes = {proximo}
                t_txt = (
                    _conteudo(tarefas[-1])
                    if isinstance(tarefas, list) and tarefas
                    else (_conteudo(tarefas) if tarefas else None)
                )
                if t_txt:
                    ultima_tarefa[proximo] = t_txt
            else:
                ramos_pendentes = set()
            continue
        if no not in WORKERS:
            continue
        rotulo = no
        if no == "Analyzer":
            passagens_analyzer += 1
            rotulo = "Analyzer" if passagens_analyzer == 1 else f"Analyzer ({passagens_analyzer})"
        sup = supervisor or {}
        tarefas = sup.get("messages") or []

        if sup.get("next_agent") == PARALELO and isinstance(tarefas, list) and len(tarefas) >= 2:
            t_ana, t_inv = _extrair_tarefas_paralelo(tarefas)
            entrada = t_ana if no == "Analyzer" else t_inv
        else:
            entrada_direta = (
                _conteudo(tarefas[-1])
                if isinstance(tarefas, list) and tarefas
                else (_conteudo(tarefas) if tarefas else None)
            )
            entrada = entrada_direta if entrada_direta is not None else ultima_tarefa.get(no)

        msgs_saida = dados.get("messages")
        if isinstance(msgs_saida, list) and msgs_saida:
            saida = _conteudo(msgs_saida[-1])
        elif msgs_saida is not None:
            saida = _conteudo(msgs_saida)
        elif not dados and update:
            saida = _conteudo(update)
        else:
            saida = ""

        falhas_ant = falhas_seguidas.get(no, 0)
        tentativas_dict = _dict(dados.get("tentativas"))
        tentativa_num = tentativas_dict.get(no) or (falhas_ant + 1)
        erro_obj = _extrair_erro(no, dados, saida, tentativa_num)
        reenvio = (falhas_ant > 0) or (sup.get("loop_count") == 0 and bool(sup.get("decidido_por")))
        if erro_obj is not None:
            falhas_seguidas[no] = tentativa_num
        else:
            falhas_seguidas[no] = 0

        pesquisa_obj = _extrair_pesquisa(dados) if no == "Investigator" else None

        numero_atual = passo_numero if passo_numero > 0 else (len(passos) + 1)
        passos.append(Passo(
            numero=numero_atual,
            agente=no,
            rotulo=rotulo,
            decidido_por=sup.get("decidido_por"),
            raciocinio=sup.get("supervisor_reasoning"),
            entrada=entrada,
            saida=saida,
            pesquisa=pesquisa_obj,
            erro=erro_obj,
            tentativa=tentativa_num,
            reenvio=reenvio,
            desistiu=False,
        ))
        indice_evento_passo.append(idx_ev)
        ramos_pendentes.discard(no)
        if not ramos_pendentes:
            supervisor = None

    for idx_p, p in enumerate(passos):
        if p.erro is None:
            continue
        rodou_depois = any(p2.agente == p.agente for p2 in passos[idx_p + 1:])
        if rodou_depois:
            p.desistiu = False
        elif p.erro.tipo == "permanente" or p.erro.tentativas >= MAX_TENTATIVAS:
            p.desistiu = True
        else:
            ev_pos = eventos[indice_evento_passo[idx_p] + 1:]
            avancou = any(
                n == "Consolidador" or (n == "Supervisor" and _dict(u).get("next_agent") not in (None, p.agente))
                for n, u in ev_pos
            )
            p.desistiu = avancou

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
        return "Analyzer" if passo_atual == 1 else f"Analyzer ({passo_atual})"
    if proximo == PARALELO:
        return "Analyzer e Investigator"
    return proximo


def status_execucao(ticker: str, rotulo: Optional[str] = None) -> str:
    """Texto do status exibido enquanto o agente está executando."""
    ticker_str = str(ticker) if ticker is not None else ""
    return f"Analisando {ticker_str}: {rotulo}..." if rotulo else f"Analisando {ticker_str}..."


def _estado_em_progresso(
    eventos: list[tuple[str, dict]],
    passos: Optional[list[Passo]] = None,
) -> tuple[list[str], str, Optional[str], Optional[str], Optional[int], bool]:
    """Calcula quem está rodando agora: (agentes_ativos, rotulo_ativo, decisao, raciocinio, numero, reenvio).

    No passo paralelo (Send), quando um ramo termina antes do outro, mantém apenas o ramo pendente
    como ativo até que ambos terminem.
    """
    if any(no == "Consolidador" for no, _ in eventos):
        return [], "", None, None, None, False
    if passos is None:
        passos = montar_passos(eventos)

    for i in range(len(eventos) - 1, -1, -1):
        no, u = eventos[i]
        if no == "Supervisor":
            sup = _dict(u)
            proximo = sup.get("next_agent")
            decisao = sup.get("decidido_por")
            raciocinio = sup.get("supervisor_reasoning")
            reenvio = sup.get("loop_count") == 0 and bool(decisao)
            if proximo == "FINISH":
                num = max((p.numero for p in passos), default=0) + 1
                return ["Consolidador"], "Consolidador", decisao, raciocinio, num, False
            if proximo == PARALELO:
                completados = {n for n, _ in eventos[i + 1:] if n in RAMOS_PARALELO}
                pendentes = [r for r in RAMOS_PARALELO if r not in completados]
                num = sum(
                    1 for n, d in eventos[:i + 1]
                    if n == "Supervisor" and (_dict(d).get("next_agent") == PARALELO or _dict(d).get("next_agent") in WORKERS)
                )
                if len(pendentes) == 2:
                    rotulo = "Analyzer e Investigator"
                elif len(pendentes) == 1:
                    rotulo = pendentes[0]
                else:
                    rotulo = ""
                return pendentes, rotulo, decisao, raciocinio, num, False
            if proximo in WORKERS:
                ja_concluiu = any(n == proximo for n, _ in eventos[i + 1:])
                if ja_concluiu:
                    return [], "", None, None, None, False
                passagens_analyzer = sum(1 for p in passos if p.agente == "Analyzer")
                rotulo = rotulo_agente_em_execucao(proximo, passagens_analyzer)
                num = sum(
                    1 for n, d in eventos[:i + 1]
                    if n == "Supervisor" and (_dict(d).get("next_agent") == PARALELO or _dict(d).get("next_agent") in WORKERS)
                )
                return [proximo], rotulo, decisao, raciocinio, num, reenvio
            break
    return [], "", None, None, None, False


def rotulo_em_execucao(eventos: list[tuple[str, dict]]) -> str:
    """Rótulo do(s) agente(s) ainda em execução a partir do histórico de eventos."""
    _, rotulo, _, _, _, _ = _estado_em_progresso(eventos)
    return rotulo


def resumo_em_progresso(eventos: list[tuple[str, dict]]) -> str:
    """Markdown com a linha do tempo ao vivo: passos concluídos e o agente rodando agora com o motivo."""
    passos = montar_passos(eventos)
    consolidou = any(no == "Consolidador" for no, _ in eventos)
    linhas: list[str] = ["**Passos da análise**"]

    for p in passos:
        decisao = ROTULO_DECISAO.get(p.decidido_por or "")
        via = f" *(via {decisao})*" if decisao else ""
        nota_reenvio = " *(reenvio do coordenador)*" if p.reenvio else ""
        if p.erro is not None:
            tipo_erro = "erro permanente" if p.erro.tipo == "permanente" else "erro temporário"
            if p.desistiu:
                linhas.append(
                    f"- :material/error: **{p.numero} · {p.rotulo}**{via}{nota_reenvio} — "
                    f"falhou ({tipo_erro}); etapa ficou de fora"
                )
            else:
                linhas.append(
                    f"- :material/warning: **{p.numero} · {p.rotulo}**{via}{nota_reenvio} — "
                    f"falhou na {p.tentativa}ª rodada ({tipo_erro})"
                )
        else:
            acao = DESCRICAO_CONCLUIDA.get(p.agente, DESCRICAO_CONCLUIDA.get(p.rotulo, "concluiu a etapa"))
            linhas.append(f"- :material/check_circle: **{p.numero} · {p.rotulo}**{via}{nota_reenvio} — {acao}")

    proximo_num = max((p.numero for p in passos), default=0) + 1
    if consolidou:
        decisao = ROTULO_DECISAO.get(decisao_do_fim(eventos) or "")
        via = f" *(via {decisao})*" if decisao else ""
        linhas.append(f"- :material/check_circle: **{proximo_num} · Consolidador**{via} — montou o relatório")
    else:
        _, rotulo_ativo, decisao_ativa, raciocinio_ativo, numero_ativo, reenvio_ativo = _estado_em_progresso(eventos, passos)
        if rotulo_ativo:
            num_exibido = numero_ativo if numero_ativo is not None else proximo_num
            decisao = ROTULO_DECISAO.get(decisao_ativa or "")
            detalhes = []
            if reenvio_ativo:
                detalhes.append("reenvio do coordenador")
            if decisao:
                detalhes.append(f"decidido por {decisao}")
            via = f" *({', '.join(detalhes)})*" if detalhes else ""
            linhas.append(f"- :material/pending: **{num_exibido} · {rotulo_ativo}** — rodando agora{via}")
            if raciocinio_ativo is not None and str(raciocinio_ativo).strip():
                linhas.append(f"  > _{escapar_markdown(str(raciocinio_ativo))}_")
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
         ativo: bool = False, reenvio: bool = False, falhou: bool = False) -> str:
    """Seta cheia do Supervisor para o agente: número da ordem, quem decidiu e o raciocínio no tooltip."""
    atributos = []
    sufixo = " (reenvio)" if reenvio else ""
    if falhou:
        sufixo += " · falhou"
    if decidido_por in ROTULO_DECISAO:
        cor = COR_INTERROMPIDO if falhou else COR_DECISAO[decidido_por]
        atributos += [f'label="{numero} · {ROTULO_DECISAO[decidido_por]}{sufixo}"', f'color="{cor}"', f'fontcolor="{cor}"']
    else:
        atributos.append(f'label="{numero}{sufixo}"')
        if falhou:
            atributos += [f'color="{COR_INTERROMPIDO}"', f'fontcolor="{COR_INTERROMPIDO}"']
    if raciocinio is not None and str(raciocinio) != "":
        atributos.append(f'tooltip="{_texto_dot(raciocinio)}"')
    if ativo:
        atributos.append('penwidth=2.5')
        atributos.append('style="bold"')
    return f"  supervisor -> {destino} [{', '.join(atributos)}];"


def _no(nome: str, rotulo: str, cor: str, rodou: bool, ativo: bool = False, desistiu: bool = False) -> str:
    if ativo:
        fundo = FUNDO_ATIVO.get(rotulo, "#fffde7")
        return (f'  {nome} [label="{rotulo}\\n(rodando agora)", color="{cor}", fontcolor="{cor}", '
                f'fillcolor="{fundo}", penwidth=3, style="rounded,filled,bold"];')
    if desistiu:
        return (f'  {nome} [label="{rotulo}\\n(desistiu)", color="{COR_INTERROMPIDO}", '
                f'fontcolor="{COR_INTERROMPIDO}", fillcolor="#ffebee", style="rounded,filled,dashed"];')
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
    reenvio_ativo: bool = False,
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
    desistiram = {
        ag for ag in rodaram
        if any(p.desistiu for p in passos if p.agente == ag)
        and not any(p.erro is None for p in passos if p.agente == ag)
    }
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
            desistiu=(agente in desistiram and not (em_progresso and agente in ativos)),
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
            linhas.append(_ida(
                destino,
                passo.numero,
                passo.decidido_por,
                passo.raciocinio,
                reenvio=passo.reenvio,
                falhou=(passo.erro is not None),
            ))
    for agente in rodaram:
        destino = NO_DO_AGENTE.get(agente)
        if destino:
            cor_volta = COR_INTERROMPIDO if agente in desistiram else COR_VOLTA
            # dir=back: a seta aponta para o Supervisor, mas o desenho mantém a hierarquia (volta reta, sem laço)
            linhas.append(f'  supervisor -> {destino} [dir=back, style=dashed, color="{cor_volta}", '
                          'arrowsize=0.7];')

    proximo_numero = numero_ativo if numero_ativo is not None else (max((p.numero for p in passos), default=0) + 1)
    if em_progresso:
        for ag in WORKERS:
            if ag in ativos:
                destino = NO_DO_AGENTE.get(ag)
                if destino:
                    linhas.append(_ida(
                        destino,
                        proximo_numero,
                        decisao_ativa,
                        raciocinio_ativo,
                        ativo=True,
                        reenvio=reenvio_ativo,
                    ))
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
    agentes_ativos, _, decisao_ativa, raciocinio_ativo, numero_ativo, reenvio_ativo = _estado_em_progresso(eventos, passos)

    return dot_do_caminho(
        passos=passos,
        decisao_fim=None,
        consolidou=False,
        em_execucao=agentes_ativos,
        decisao_ativa=decisao_ativa,
        raciocinio_ativo=raciocinio_ativo,
        em_progresso=True,
        numero_ativo=numero_ativo,
        reenvio_ativo=reenvio_ativo,
    )


dot_em_progresso = dot_do_caminho_em_progresso


# ---------------------------------------------------------------------------
# Subgrafo de pesquisa do Investigator (agents/pesquisa.py)
# ---------------------------------------------------------------------------

def limpar_tags_externas(texto: str) -> str:
    """Remove o envelope <conteudo_externo ...>...</conteudo_externo> para exibição limpa no dashboard."""
    if not isinstance(texto, str):
        return ""
    return re.sub(rf"</?{TAG_CONTEUDO_EXTERNO}[^>]*>\n?", "", texto).strip()


def agrupar_achados_por_rodada(pesquisa: PesquisaFeita) -> list[tuple[int, list[dict]]]:
    """Agrupa os achados do subgrafo por rodada (1 = perguntas iniciais; 2+ = voltas pedidas pelo crítico)."""
    por_rodada: dict[int, list[dict]] = {}
    for item in pesquisa.achados or []:
        if not isinstance(item, dict):
            continue
        rodada = int(item.get("rodada") or 1)
        por_rodada.setdefault(rodada, []).append(item)
    return sorted(por_rodada.items(), key=lambda par: par[0])


def resumo_pesquisa(pesquisa: PesquisaFeita) -> str:
    """Resumo em uma linha do que o subgrafo de pesquisa do Investigator executou."""
    n_perguntas = len(pesquisa.perguntas or [])
    achados = pesquisa.achados or []
    total_buscas = len(achados)
    com_texto = sum(1 for a in achados if isinstance(a, dict) and str(a.get("texto", "")).strip())
    voltas = int(pesquisa.voltas or 0)

    partes = [
        f"{n_perguntas} {'pergunta gerada' if n_perguntas == 1 else 'perguntas geradas'}",
        f"{com_texto}/{total_buscas} {'busca com resultado' if total_buscas == 1 else 'buscas com resultado'}",
    ]
    if total_buscas > 0 and com_texto == 0:
        partes.append("diagnóstico indeterminado em código (sem chamar o crítico)")
    elif voltas == 0:
        partes.append("aprovado de primeira pelo crítico (0 voltas extras)")
    else:
        partes.append(f"{voltas} {'volta extra pedida' if voltas == 1 else 'voltas extras pedidas'} pelo crítico")
    return " · ".join(partes)


def dot_do_subgrafo_pesquisa(pesquisa: PesquisaFeita) -> str:
    """DOT do subgrafo de pesquisa causal do Investigator (preparar → gerar_perguntas → buscar → sintetizar → criticar)."""
    achados = pesquisa.achados or []
    n_iniciais = sum(1 for a in achados if isinstance(a, dict) and int(a.get("rodada") or 1) == 1)
    if n_iniciais == 0:
        n_iniciais = len(pesquisa.perguntas or [])
    total_buscas = len(achados)
    com_achado = sum(1 for a in achados if isinstance(a, dict) and str(a.get("texto", "")).strip())
    voltas = int(pesquisa.voltas or 0)
    sem_achados = total_buscas > 0 and com_achado == 0

    rotulo_perguntas = f"gerar_perguntas\\n({n_iniciais} {'pergunta' if n_iniciais == 1 else 'perguntas'})"
    rotulo_buscar = f"buscar (Send)\\n({com_achado}/{total_buscas} com achados)"
    rotulo_sintetizar = "sintetizar\\n(indeterminado em código)" if sem_achados else "sintetizar\\n(DiagnosticoPesquisa)"
    if sem_achados:
        rotulo_criticar = "criticar\\n(não precisou)"
    elif voltas == 0:
        rotulo_criticar = "criticar\\n(aprovado de 1ª)"
    else:
        rotulo_criticar = f"criticar\\n({voltas} {'volta' if voltas == 1 else 'voltas'})"

    linhas = [
        "digraph subgrafo_pesquisa {",
        "  rankdir=LR;",
        '  bgcolor="transparent";',
        "  nodesep=0.4; ranksep=0.5;",
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, penwidth=1.8, margin="0.16,0.08"];',
        '  edge [fontname="Helvetica", fontsize=9, penwidth=1.4];',
        '  preparar [label="preparar\\n(trimestrais em código)", color="#2e7d32", fontcolor="#2e7d32", fillcolor="#e8f5e9"];',
        f'  gerar_perguntas [label="{rotulo_perguntas}", color="#1565c0", fontcolor="#1565c0", fillcolor="#e3f2fd"];',
        f'  buscar [label="{rotulo_buscar}", color="#2e7d32", fontcolor="#2e7d32", fillcolor="#e8f5e9"];',
        f'  sintetizar [label="{rotulo_sintetizar}", color="#1565c0", fontcolor="#1565c0", fillcolor="#e3f2fd"];',
        f'  criticar [label="{rotulo_criticar}", color="#e05555", fontcolor="#e05555", fillcolor="#fff8f8"];',
        f'  fim_pesquisa [label="Diagnóstico", shape=oval, style="filled", color="{COR_APAGADA}", fontcolor="#555555", fillcolor="#fafafa"];',
        '  preparar -> gerar_perguntas;',
        '  gerar_perguntas -> buscar [label="Send"];',
        '  buscar -> sintetizar;',
        '  sintetizar -> criticar;',
    ]
    if voltas > 0:
        linhas.append(
            f'  criticar -> buscar [label="{voltas}x lacunas (Send)", style=dashed, color="#e05555", fontcolor="#e05555"];'
        )
    linhas.append('  criticar -> fim_pesquisa [label="aprovado"];')
    linhas.append("}")
    return "\n".join(linhas)


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
