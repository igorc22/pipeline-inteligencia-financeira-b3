"""Dashboard em Streamlit: relatório primeiro, caminho da análise e state em abas (D46).

Rodar: make streamlit  (ou: uv run streamlit run dashboard/app.py)

Só o botão Analisar roda o grafo (gasta créditos). O resultado fica em st.session_state, então
trocar de aba ou abrir um expansor não roda nada de novo.
"""
from typing import Optional

import streamlit as st
from langchain_core.messages import HumanMessage

from dashboard.visao import (
    ROTULO_DECISAO,
    decisao_do_fim,
    dot_do_caminho,
    montar_passos,
    parou_no_hard_stop,
    separar_indicador,
    state_para_json,
)
from fluxo_financeiro import app as grafo

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
            erro = str(exc)
            status.update(label=f"A análise de {ticker} falhou", state="error", expanded=False)
    return {"ticker": ticker, "eventos": eventos, "state": state, "erro": erro}


def _mensagem_final(resultado: dict) -> Optional[str]:
    """Markdown que o Consolidador escreveu (relatório formatado ou o de emergência)."""
    for no, update in reversed(resultado["eventos"]):
        if no == "Consolidador" and update.get("messages"):
            return update["messages"][-1].content
    return None


def _lista(titulo: str, itens: list[str]) -> None:
    if itens:
        st.markdown(f"#### {titulo}")
        st.markdown("\n".join(f"- {item}" for item in itens))


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
            st.markdown(final)
        else:
            st.info("Sem relatório: a análise não chegou ao fim. Veja a aba **Como foi feito**.")
        return

    st.markdown(relatorio.resumo)

    sinais = state.get("sinais_anomalia") or []
    if sinais:
        st.warning("**Sinais de anomalia calculados em código:**\n"
                   + "\n".join(f"- {s.descricao}" for s in sinais))

    if relatorio.indicadores:
        st.markdown("#### Indicadores")
        separados = [separar_indicador(i) for i in relatorio.indicadores]
        quadros = [(nome, valor) for nome, valor in separados if valor is not None]
        for inicio in range(0, len(quadros), COLUNAS_INDICADORES):
            colunas = st.columns(COLUNAS_INDICADORES)
            for coluna, (nome, valor) in zip(colunas, quadros[inicio:inicio + COLUNAS_INDICADORES]):
                coluna.metric(nome, valor)
        soltos = [nome for nome, valor in separados if valor is None]
        if soltos:
            st.markdown("\n".join(f"- {s}" for s in soltos))

    _lista("Riscos", relatorio.riscos)
    if relatorio.limitacoes:
        st.warning("**Limitações da análise:**\n" + "\n".join(f"- {l}" for l in relatorio.limitacoes))
    if relatorio.contexto:
        st.markdown("#### Notícias e setor")
        st.markdown(relatorio.contexto)
    if relatorio.diagnostico:
        st.markdown("#### Diagnóstico da anomalia")
        st.markdown(relatorio.diagnostico)

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

    st.graphviz_chart(dot_do_caminho(passos, decisao_do_fim(eventos)))
    st.caption("Cada seta diz quem decidiu o passo: **guard** (regra em código), **LLM** (o Supervisor "
               "consultou o modelo) ou **hard stop** (limite de passagens).")

    for passo in passos:
        with st.container(border=True):
            decisao = ROTULO_DECISAO.get(passo.decidido_por or "")
            st.markdown(f"**{passo.numero} · {passo.rotulo}**" + (f" · decidido por *{decisao}*" if decisao else ""))
            if passo.raciocinio:
                st.caption(f"Raciocínio do Supervisor: {passo.raciocinio}")
            entrada, saida = st.columns([1, 2])
            with entrada:
                st.markdown("**Entrada (tarefa recebida)**")
                st.markdown(passo.entrada or "_sem tarefa registrada_")
            with saida:
                st.markdown("**Saída**")
                with st.expander(_previa(passo.saida) or "(vazia)"):
                    if passo.agente == "YFinance":  # texto alinhado por espaços: monoespaçado
                        st.code(passo.saida, language=None, wrap_lines=True)
                    else:
                        st.markdown(passo.saida)


def aba_state(resultado: dict) -> None:
    if resultado["state"] is None:
        st.info("O state final não chegou (a análise foi interrompida).")
        return
    st.json(state_para_json(resultado["state"]), expanded=1)


st.set_page_config(page_title="Pipeline B3", layout="wide")
st.title("Pipeline de Inteligência Financeira")
st.caption("Análise de ações da B3 por agentes: dados, notícias, setor e investigação de anomalias.")

campo, botao = st.columns([4, 1], vertical_alignment="bottom")
ticker_digitado = campo.text_input("Ticker da B3", key="ticker", placeholder="ex: PETR4, VALE3, WEGE3")
if botao.button("Analisar", type="primary", use_container_width=True):
    ticker = ticker_digitado.strip().upper()
    if not ticker:
        st.warning("Digite um ticker antes de analisar.")
    else:
        st.session_state["resultado"] = rodar_analise(ticker)

resultado = st.session_state.get("resultado")
if resultado:
    if resultado["erro"]:
        st.error(f"A análise falhou: {resultado['erro']}")
    relatorio_tab, fluxo_tab, state_tab = st.tabs(["Relatório", "Como foi feito", "State (JSON)"])
    with relatorio_tab:
        aba_relatorio(resultado)
    with fluxo_tab:
        aba_como_foi_feito(resultado)
    with state_tab:
        aba_state(resultado)
