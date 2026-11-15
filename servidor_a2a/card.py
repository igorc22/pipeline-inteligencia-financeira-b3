from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill

URL_PADRAO = "http://pipeline-b3:10001/"
VERSAO = "1.0.0"


def montar_card(url: str = URL_PADRAO) -> AgentCard:
    """Agent Card do pipeline: o que outros agentes leem para saber o que ele faz e onde chamá-lo."""
    return AgentCard(
        name="Pipeline B3",
        description=(
            "Analisa uma ação da B3: dados de mercado, métricas de risco, notícias, contexto do setor "
            "e, quando há anomalia, o diagnóstico da causa. Devolve um relatório em markdown e o mesmo "
            "relatório estruturado em JSON. Não recomenda compra nem venda."
        ),
        version=VERSAO,
        supported_interfaces=[AgentInterface(url=url, protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text/plain"],
        default_output_modes=["text/markdown", "application/json"],
        skills=[AgentSkill(
            id="analisar_acao",
            name="Analisar ação da B3",
            description=(
                "Recebe um ticker da B3 (ex: VALE3), sozinho ou numa frase, um por mensagem. "
                "A análise leva de 20 a 30 segundos."
            ),
            tags=["b3", "ações", "análise fundamentalista", "risco"],
            examples=["Analise VALE3", "WEGE3"],
        )],
    )
