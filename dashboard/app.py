"""Dashboard em Streamlit: relatório primeiro, caminho da análise e state em abas.

Rodar: make streamlit  (ou: uv run streamlit run dashboard/app.py)

Só o botão Analisar roda o grafo (gasta créditos). O resultado fica em st.session_state, então
trocar de aba ou abrir um expansor não roda nada de novo. Enquanto a análise roda, o campo e o
botão ficam travados: um clique no meio reiniciaria o script e jogaria fora a análise já paga.
"""
from typing import Optional

import streamlit as st
from langchain_core.messages import HumanMessage

from dashboard.visao import (
    ROTULO_DECISAO,
    Passo,
    _ultima_mensagem,
    agrupar_achados_por_rodada,
    decisao_do_fim,
    dividir_indicadores,
    dot_do_caminho,
    dot_do_caminho_em_progresso,
    dot_do_subgrafo_pesquisa,
    escapar_markdown,
    limpar_tags_externas,
    montar_passos,
    parou_no_hard_stop,
    passo_do_consolidador,
    raciocinio_do_fim,
    resumo_em_progresso,
    resumo_pesquisa,
    rotulo_agente_em_execucao,
    rotulo_em_execucao,
    state_para_json,
    status_execucao,
)
from fluxo_financeiro import app as grafo
from fluxo_financeiro.shared.types import PesquisaFeita
from fluxo_financeiro.shared.utils import TICKER_INVALIDO, logger, validar_ticker

COLUNAS_INDICADORES = 4
TAMANHO_PREVIA = 90


def _descrever_erro(exc: Exception) -> str:
    """Tipo + mensagem: algumas exceções (ex: TimeoutError()) não têm texto nenhum."""
    texto = str(exc).strip()
    return f"{type(exc).__name__}: {texto}" if texto else type(exc).__name__


def rodar_analise(ticker: str) -> dict:
    """Roda o grafo mostrando cada passo num st.status e atualizando o diagrama ao vivo."""
    eventos: list[tuple[str, dict]] = []
    state: Optional[dict] = None
    erro: Optional[str] = None
    with st.status(f"Analisando {ticker}...", expanded=True) as status:
        col_grafo, col_passos = st.columns([3, 2], vertical_alignment="center")
        with col_grafo.container(horizontal_alignment="center"):
            diagrama = st.empty()
        with col_passos.container(border=True):
            painel_passos = st.empty()
        diagrama.graphviz_chart(dot_do_caminho_em_progresso(eventos))
        painel_passos.markdown(resumo_em_progresso(eventos))
        try:
            pedido = {"messages": [HumanMessage(f"Analise a ação {ticker}")]}
            for modo, dado in grafo.stream(pedido, stream_mode=["updates", "values"]):
                if modo == "values":
                    state = dado
                    continue
                for no, update in dado.items():
                    update = update or {}  # nó que não devolve nada chega como None
                    eventos.append((no, update))
                    if no == "Supervisor":
                        rotulo = rotulo_agente_em_execucao(update.get("next_agent"))
                        status.update(label=status_execucao(ticker, rotulo), state="running", expanded=True)
                    else:
                        rotulo_pendente = rotulo_em_execucao(eventos)
                        if rotulo_pendente:
                            status.update(label=status_execucao(ticker, rotulo_pendente), state="running", expanded=True)
                    diagrama.graphviz_chart(dot_do_caminho_em_progresso(eventos))
                    painel_passos.markdown(resumo_em_progresso(eventos))
            if any(no == "Consolidador" for no, _ in eventos):
                status.update(label=f"Análise de {ticker} concluída", state="complete", expanded=False)
            else:
                erro = "A análise foi interrompida antes da consolidação."
                status.update(label=f"A análise de {ticker} foi interrompida", state="error", expanded=False)
                diagrama.graphviz_chart(dot_do_caminho(montar_passos(eventos), decisao_do_fim(eventos), consolidou=False))
        except Exception as exc:  # o erro aparece na tela; o que já chegou continua visível
            logger.exception(f"[dashboard] análise de {ticker} falhou")
            erro = _descrever_erro(exc)
            status.update(label=f"A análise de {ticker} falhou", state="error", expanded=False)
            diagrama.graphviz_chart(dot_do_caminho(montar_passos(eventos), decisao_do_fim(eventos), consolidou=False))
    return {"ticker": ticker, "eventos": eventos, "state": state, "erro": erro}


def _mensagem_final(resultado: dict) -> Optional[str]:
    """Markdown que o Consolidador escreveu (relatório formatado ou o de emergência)."""
    for no, update in reversed(resultado["eventos"]):
        if no == "Consolidador":
            return _ultima_mensagem(update) or None
    return None


def _md(texto: str) -> None:
    st.markdown(escapar_markdown(texto))


def _lista_md(itens: list[str]) -> str:
    return "\n".join(f"- {escapar_markdown(item)}" for item in itens)


def aba_relatorio(resultado: dict) -> None:
    ticker = resultado["ticker"]
    state = resultado["state"] or {}
    relatorio = state.get("relatorio")
    final = _mensagem_final(resultado)

    st.subheader(f"Relatório: {ticker}")
    if relatorio is None:
        if final:
            st.warning("O relatório estruturado não foi gerado (o LLM do Consolidador falhou). "
                       "Abaixo, o texto que o sistema montou com as respostas dos agentes.")
            _md(final)
        else:
            st.info("Sem relatório: a análise não chegou ao fim. Veja a aba **Como foi feito**.")
        return

    _md(relatorio.resumo)

    sinais = state.get("sinais_anomalia") or []
    if sinais:
        st.warning("**Sinais de anomalia calculados em código:**\n" + _lista_md([s.descricao for s in sinais]))

    if relatorio.indicadores:
        st.markdown("#### Indicadores")
        quadros, linhas = dividir_indicadores(relatorio.indicadores)
        for inicio in range(0, len(quadros), COLUNAS_INDICADORES):
            colunas = st.columns(COLUNAS_INDICADORES)
            for coluna, (nome, valor) in zip(colunas, quadros[inicio:inicio + COLUNAS_INDICADORES]):
                coluna.metric(escapar_markdown(nome), valor)
        if linhas:
            st.markdown(_lista_md(linhas))

    if relatorio.riscos:
        st.markdown("#### Riscos")
        st.markdown(_lista_md(relatorio.riscos))
    if relatorio.limitacoes:
        st.warning("**Limitações da análise:**\n" + _lista_md(relatorio.limitacoes))
    if relatorio.contexto:
        st.markdown("#### Notícias e setor")
        _md(relatorio.contexto)
    if relatorio.diagnostico:
        st.markdown("#### Diagnóstico da anomalia")
        _md(relatorio.diagnostico)

    if final:
        st.download_button("Baixar relatório (.md)", data=final, file_name=f"relatorio_{ticker}.md",
                           mime="text/markdown")


def _previa(texto: Optional[str]) -> str:
    if not texto:
        return ""
    linha = " ".join(str(texto).split())
    return linha if len(linha) <= TAMANHO_PREVIA else linha[:TAMANHO_PREVIA].rstrip() + "…"


def aba_como_foi_feito(resultado: dict) -> None:
    eventos = resultado["eventos"]
    passos = montar_passos(eventos)
    if not passos:
        st.info("Nenhum agente chegou a rodar.")
        return
    if parou_no_hard_stop(eventos):
        st.warning("O fluxo parou pelo limite de 6 passagens do Supervisor (hard stop).")

    consolidou = any(no == "Consolidador" for no, _ in eventos) and not resultado.get("erro")
    proximo_num = max((p.numero for p in passos), default=0) + 1
    final = passo_do_consolidador(eventos, numero=proximo_num)
    with st.container(horizontal_alignment="center"):
        st.graphviz_chart(dot_do_caminho(
            passos,
            decisao_do_fim(eventos),
            consolidou=consolidou,
            raciocinio_fim=raciocinio_do_fim(eventos),
        ))
    st.caption("**Seta cheia:** o Supervisor manda um agente trabalhar. O número é a ordem e o rótulo diz "
               "quem decidiu: **guard** (regra em código), **LLM** (o Supervisor consultou o modelo) ou "
               "**hard stop** (limite de passagens); passe o mouse para ver o raciocínio. "
               "**Seta tracejada:** o agente devolve o resultado ao Supervisor.")

    for passo in passos + ([final] if final else []):
        _card_do_passo(passo)


def _bloco_subgrafo_pesquisa(pesquisa: PesquisaFeita) -> None:
    """Mostra o subgrafo de pesquisa do Investigator: diagrama interno, histórico trimestral e buscas por rodada."""
    st.markdown(f"**Subgrafo de pesquisa causal:** {escapar_markdown(resumo_pesquisa(pesquisa))}")
    with st.container(horizontal_alignment="center"):
        st.graphviz_chart(dot_do_subgrafo_pesquisa(pesquisa))

    if pesquisa.historico and pesquisa.historico.strip():
        with st.expander("Histórico trimestral lido em código (preparar)"):
            st.code(pesquisa.historico, language=None, wrap_lines=True)

    rodadas = agrupar_achados_por_rodada(pesquisa)
    for num_rodada, itens in rodadas:
        origem_rodada = (
            "Perguntas iniciais (gerar_perguntas)"
            if num_rodada == 1
            else f"Lacunas pedidas pelo crítico ({num_rodada - 1}ª volta extra)"
        )
        n_itens = len(itens)
        titulo = f"Rodada {num_rodada} · {origem_rodada} ({n_itens} {'busca' if n_itens == 1 else 'buscas'} via Send)"
        with st.expander(titulo):
            for idx, item in enumerate(itens, start=1):
                pergunta = str(item.get("pergunta") or "").strip()
                texto_limpo = limpar_tags_externas(str(item.get("texto") or ""))
                st.markdown(f"**{idx}. {escapar_markdown(pergunta)}**")
                if texto_limpo:
                    _md(texto_limpo)
                else:
                    st.markdown("_Busca sem resultado._")


def _card_do_passo(passo: Passo) -> None:
    with st.container(border=True):
        selo_reenvio = " *(reenvio do coordenador · loop_count +0)*" if passo.reenvio else ""
        st.markdown(f"**{passo.numero} · {passo.rotulo}**{selo_reenvio}")
        decisao = ROTULO_DECISAO.get(passo.decidido_por or "")
        if passo.raciocinio or decisao:
            quem = f"Supervisor, decidido por *{decisao}*" if decisao else "Supervisor"
            st.markdown(f"> **{quem}:** {escapar_markdown(passo.raciocinio or '')}")
        if passo.erro is not None:
            tipo_erro = "erro permanente" if passo.erro.tipo == "permanente" else "erro temporário"
            if passo.desistiu:
                st.error(
                    f"O {passo.agente} falhou na {passo.tentativa}ª rodada do nó ({tipo_erro}) e desistiu: "
                    "a análise seguiu sem esta etapa."
                )
            else:
                st.warning(
                    f"O {passo.agente} falhou na {passo.tentativa}ª rodada do nó ({tipo_erro}): "
                    "escalado ao coordenador para nova tentativa."
                )
        entrada, saida = st.columns([1, 2])
        with entrada:
            st.markdown("**Entrada (tarefa recebida)**")
            if passo.entrada:
                _md(passo.entrada)
            elif passo.agente == "Consolidador":
                st.markdown("_As respostas de todos os agentes (o Consolidador não recebe tarefa)._")
            else:
                st.markdown("_sem tarefa registrada_")
        with saida:
            st.markdown("**Saída**")
            with st.expander(escapar_markdown(_previa(passo.saida)) or "(vazia)"):
                if passo.agente == "YFinance":  # texto alinhado por espaços: monoespaçado
                    st.code(passo.saida, language=None, wrap_lines=True)
                else:
                    _md(passo.saida)
        if passo.agente == "Investigator" and passo.pesquisa is not None:
            _bloco_subgrafo_pesquisa(passo.pesquisa)


def aba_state(resultado: dict) -> None:
    if resultado["state"] is None:
        st.info("O state final não chegou (a análise foi interrompida).")
        return
    st.json(state_para_json(resultado["state"]), expanded=1)


def _pedir_analise() -> None:
    """Callback do botão: roda antes do script, então o botão já aparece travado nesta execução.

    Guarda o ticker aqui: quando o campo muda de travado para destravado, o Streamlit o trata
    como outro widget e zera o valor.
    """
    # Importado aqui para o patch no módulo de origem valer nos testes.
    from fluxo_financeiro.tools.brapi import mensagem_ticker_inexistente, ticker_existe

    digitado = st.session_state.get("ticker", "").strip()
    ticker = validar_ticker(digitado)
    if ticker:
        if ticker_existe(ticker) is False:  # só o 404 da Brapi recusa; None (sem resposta) segue
            st.session_state["aviso_ticker_inexistente"] = mensagem_ticker_inexistente(ticker)
            return
        st.session_state["ticker_pedido"] = ticker
        st.session_state["rodando"] = True
    elif digitado:
        st.session_state["aviso_ticker_invalido"] = True  # não é ticker: nem chega ao grafo
    else:
        st.session_state["aviso_ticker_vazio"] = True


st.set_page_config(page_title="Pipeline B3", layout="wide")
st.title("Pipeline de Inteligência Financeira")
st.caption("Análise de ações da B3 por agentes: dados, notícias, setor e investigação de anomalias.")

rodando = st.session_state.get("rodando", False)
if not st.session_state.get("ticker") and st.session_state.get("ticker_pedido"):
    st.session_state["ticker"] = st.session_state["ticker_pedido"]  # devolve o que foi analisado
campo, botao = st.columns([4, 1], vertical_alignment="bottom")
campo.text_input("Ticker da B3", key="ticker", placeholder="ex: PETR4, VALE3, WEGE3", disabled=rodando)
botao.button("Analisar", type="primary", use_container_width=True, on_click=_pedir_analise, disabled=rodando)

if st.session_state.pop("aviso_ticker_vazio", False):
    st.warning("Digite um ticker antes de analisar.")
if st.session_state.pop("aviso_ticker_invalido", False):
    st.warning(TICKER_INVALIDO)
aviso_inexistente = st.session_state.pop("aviso_ticker_inexistente", None)
if aviso_inexistente:
    st.warning(escapar_markdown(aviso_inexistente))

if rodando:
    try:
        st.session_state["resultado"] = rodar_analise(st.session_state["ticker_pedido"])
    finally:
        st.session_state["rodando"] = False
    st.rerun()  # redesenha com o campo e o botão destravados

resultado = st.session_state.get("resultado")
if resultado:
    if resultado["erro"]:
        st.error(f"A análise falhou: {escapar_markdown(resultado['erro'])}")
    relatorio_tab, fluxo_tab, state_tab = st.tabs(["Relatório", "Como foi feito", "State (JSON)"])
    with relatorio_tab:
        aba_relatorio(resultado)
    with fluxo_tab:
        aba_como_foi_feito(resultado)
    with state_tab:
        aba_state(resultado)
