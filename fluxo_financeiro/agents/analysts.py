from langchain.agents import create_agent
from fluxo_financeiro.shared.llm import criar_llm
from fluxo_financeiro.tools.news import buscar_noticias, buscar_noticias_web

llm = criar_llm()

ANALYZER_PROMPT = """Você é um analista financeiro conciso. O histórico traz os dados de mercado de uma ação
(mensagem do YFinance) e uma tarefa específica para você (a última mensagem do Supervisor).
Siga a tarefa do Supervisor: ela pode pedir notícias da empresa ou contexto do setor.

QUANDO USAR CADA FERRAMENTA:
- buscar_noticias_web: use primeiro. Traz o mais recente sobre a empresa e o setor, com as fontes.
- buscar_noticias: use só se buscar_noticias_web der erro ou não trouxer nada relevante.

RESPOSTA:
Escreva 1 a 2 parágrafos combinando os números do YFinance com o que encontrou.
Cite fatos concretos (datas, valores, eventos) e não invente o que não estiver nas fontes."""

analyzer_agent = create_agent(
    model=llm,
    tools=[buscar_noticias, buscar_noticias_web],
    system_prompt=ANALYZER_PROMPT,
)
