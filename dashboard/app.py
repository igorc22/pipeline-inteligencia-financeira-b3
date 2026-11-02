"""Dashboard em Streamlit: relatório primeiro, caminho da análise e state em abas (D46).

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
    decisao_do_fim,
    dividir_indicadores,
    dot_do_caminho,
    escapar_markdown,
    montar_passos,
    parou_no_hard_stop,
    state_para_json,
)
from fluxo_financeiro import app as grafo
from fluxo_financeiro.shared.utils import logger

COLUNAS_INDICADORES = 4
TAMANHO_PREVIA = 90
STATUS_ANALYZER = {1: "Analyzer buscou as notícias da empresa", 2: "Analyzer buscou o contexto do setor"}
STATUS_FIXO = {
    "YFinance": "YFinance coletou os dados de mercado",
    "Investigator": "Investigator investigou a anomalia",
    "Consolidador": "Consolidador montou o relatório",
}


def _linha_status(no: str, passagens_analyzer: int) -> Optional[str]:
    if no == "Analyzer":
        return STATUS_ANALYZER.get(passagens_analyzer, f"Analyzer: passagem {passagens_analyzer}")
    return STATUS_FIXO.get(no)


def _descrever_erro(exc: Exception) -> str:
    """Tipo + mensagem: algumas exceções (ex: TimeoutError()) não têm texto nenhum."""
    texto = str(exc).strip()
    return f"{type(exc).__name__}: {texto}" if texto else type(exc).__name__


def rodar_analise(ticker: str) -> dict:
    """Roda o grafo mostrando cada passo num st.status; devolve eventos, state final e erro."""
    eventos: list[tuple[str, dict]] = []
    state: Optional[dict] = None
    erro: Optional[str] = None
    passagens_analyzer = 0
    with st.status(f"Analisando {ticker}...", expanded=True) as status:
        try:
            pedido = {"messages": [HumanMessage(f"Analise a ação {ticker}")]}
            for modo, dado in grafo.stream(pedido, stream_mode=["updates", "values"]):
                if modo == "values":
                    state = dado
                    continue
                for no, update in dado.items():
                    eventos.append((no, update or {}))
                    passagens_analyzer += no == "Analyzer"
                    linha = _linha_status(no, passagens_analyzer)
                    if linha:
                        status.write(linha)
            status.update(label=f"Análise de {ticker} concluída", state="complete", expanded=False)
        except Exception as exc:  # o erro aparece na tela; o que já chegou continua visível
            logger.exception(f"[dashboard] análise de {ticker} falhou")
            erro = _descrever_erro(exc)
            status.update(label=f"A análise de {ticker} falhou", state="error", expanded=False)
    return {"ticker": ticker, "eventos": eventos, "state": state, "erro": erro}


def _mensagem_final(resultado: dict) -> Optional[str]:
    """Markdown que o Consolidador escreveu (relatório formatado ou o de emergência)."""
    for no, update in reversed(resultado["eventos"]):
        if no == "Consolidador" and update.get("messages"):
            return update["messages"][-1].content
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


def _previa(texto: str) -> str:
    linha = " ".join(texto.split())
    return linha if len(linha) <= TAMANHO_PREVIA else linha[:TAMANHO_PREVIA].rstrip() + "…"


def aba_como_foi_feito(resultado: dict) -> None:
    eventos = resultado["eventos"]
    passos = montar_passos(eventos)
    if not passos:
        st.info("Nenhum agente chegou a rodar.")
        return
    if parou_no_hard_stop(eventos):
        st.warning("O fluxo parou pelo limite de 6 passagens do Supervisor (hard stop).")

    consolidou = any(no == "Consolidador" for no, _ in eventos)
    st.graphviz_chart(dot_do_caminho(passos, decisao_do_fim(eventos), consolidou=consolidou))
    st.caption("Cada seta diz quem decidiu o passo: **guard** (regra em código), **LLM** (o Supervisor "
               "consultou o modelo) ou **hard stop** (limite de passagens).")

    for passo in passos:
        with st.container(border=True):
            decisao = ROTULO_DECISAO.get(passo.decidido_por or "")
            st.markdown(f"**{passo.numero} · {passo.rotulo}**" + (f" · decidido por *{decisao}*" if decisao else ""))
            if passo.raciocinio:
                st.caption(escapar_markdown(f"Raciocínio do Supervisor: {passo.raciocinio}"))
            entrada, saida = st.columns([1, 2])
            with entrada:
                st.markdown("**Entrada (tarefa recebida)**")
                _md(passo.entrada) if passo.entrada else st.markdown("_sem tarefa registrada_")
            with saida:
                st.markdown("**Saída**")
                with st.expander(escapar_markdown(_previa(passo.saida)) or "(vazia)"):
                    if passo.agente == "YFinance":  # texto alinhado por espaços: monoespaçado
                        st.code(passo.saida, language=None, wrap_lines=True)
                    else:
                        _md(passo.saida)


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
    ticker = st.session_state.get("ticker", "").strip().upper()
    if ticker:
        st.session_state["ticker_pedido"] = ticker
        st.session_state["rodando"] = True
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
